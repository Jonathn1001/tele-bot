"""Notion source + write client for the weekly review feature.

Reads the current week's "Weekly To-do List" page under a parent container and,
after the Sunday review, clones it into next week's page. Network I/O is kept
separate from pure parsing so the parsing is fixture-testable without a network.
Fails soft — a Notion outage never crashes the bot.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

import config

logger = logging.getLogger(__name__)

API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
_TIMEOUT = 30.0
_PAGE_SIZE = 100

# Block types the create API accepts and the template uses. Anything else in a
# cloned page is skipped (logged) rather than failing the whole create.
CREATABLE_TYPES = frozenset(
    {
        "paragraph", "heading_1", "heading_2", "heading_3",
        "bulleted_list_item", "numbered_list_item", "to_do", "toggle",
        "quote", "callout", "divider", "code", "column_list", "column",
    }
)

# Heading prefix written above a review; also the idempotency marker (a page
# already carrying a heading_2 starting with this string is not written again).
REVIEW_MARKER = "📝 Weekly Review"
_MAX_PARAGRAPH_CHARS = 1900  # under Notion's 2000-char rich_text content cap

_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_MONTH_LOOKUP: dict[str, int] = {}
for _i, _name in enumerate(_MONTH_NAMES, start=1):
    _MONTH_LOOKUP[_name.lower()] = _i
    _MONTH_LOOKUP[_name[:3].lower()] = _i  # accept 3-letter abbreviations (Aug, Sep)

# Title date range, e.g. "... (July 20 - July 26)" — tolerant of the emoji
# prefix, extra whitespace, and an en-dash separator.
TITLE_RANGE_RE = re.compile(
    r"\(\s*([A-Za-z]{3,9})\s+(\d{1,2})\s*[-–]\s*([A-Za-z]{3,9})\s+(\d{1,2})\s*\)"
)


@dataclass
class WeekPage:
    id: str
    title: str
    created_time: str = ""
    start: date | None = None
    end: date | None = None


@dataclass
class Task:
    text: str
    checked: bool


@dataclass
class Day:
    name: str
    tasks: list[Task] = field(default_factory=list)


@dataclass
class Week:
    label: str
    days: list[Day] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pure helpers (no network)
# --------------------------------------------------------------------------- #

def _rich_text_plain(rich_text: list[dict] | None) -> str:
    """Concatenate the plain_text of every rich_text run (text + mentions)."""
    return "".join(rt.get("plain_text", "") for rt in (rich_text or []))


def _block_text(block: dict) -> str:
    t = block.get("type", "")
    return _rich_text_plain(block.get(t, {}).get("rich_text"))


def _page_title(page: dict) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("type") == "title":
            return _rich_text_plain(prop.get("title", []))
    return ""


def _nearest_year_date(month: int, day: int, today: date) -> date | None:
    """The (month, day) instance closest to `today` — resolves the missing year
    in titles and the Dec→Jan boundary without guessing."""
    best: date | None = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - today).days) < abs((best - today).days):
            best = cand
    return best


def parse_title_range(title: str, today: date) -> tuple[date, date] | None:
    """Parse the "(Mon D - Mon D)" range from a week-page title, resolving the
    year relative to `today`. Returns None for titles without a valid range."""
    m = TITLE_RANGE_RE.search(title)
    if not m:
        return None
    mon1, d1, mon2, d2 = m.groups()
    m1 = _MONTH_LOOKUP.get(mon1.lower())
    m2 = _MONTH_LOOKUP.get(mon2.lower())
    if not m1 or not m2:
        return None
    start = _nearest_year_date(m1, int(d1), today)
    end = _nearest_year_date(m2, int(d2), today)
    if start is None or end is None:
        return None
    if end < start:
        try:
            end = date(end.year + 1, end.month, end.day)
        except ValueError:
            return None
    return start, end


def _select_week_page(children: list[dict], today: date, strict: bool = False) -> WeekPage | None:
    """Pick the child_page whose title range contains `today`. When `strict`,
    return None if none contains it (used by the create idempotency guard —
    a fallback there would mistake this week's page for next week's and never
    create). When not strict, fall back to the newest candidate (lenient find)."""
    candidates: list[WeekPage] = []
    for b in children:
        if b.get("type") != "child_page":
            continue
        title = b.get("child_page", {}).get("title", "")
        rng = parse_title_range(title, today)
        if rng is None:
            continue
        candidates.append(
            WeekPage(id=b.get("id", ""), title=title,
                     created_time=b.get("created_time", ""), start=rng[0], end=rng[1])
        )
    for c in candidates:
        if c.start is not None and c.end is not None and c.start <= today <= c.end:
            return c
    if strict:
        return None
    if candidates:
        newest = max(candidates, key=lambda c: c.created_time)
        logger.warning("Notion: no week page contains %s; using newest %r", today, newest.title)
        return newest
    return None


def parse_week(blocks: list[dict], label: str) -> Week:
    """Walk a fetched block tree (blocks carry '_children') into a Week.
    Top-level bulleted_list_item texts are goals; the column_list holds the days."""
    days: list[Day] = []
    goals: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "bulleted_list_item":
            txt = _block_text(b)
            if txt:
                goals.append(txt)
        elif t == "column_list":
            for col in b.get("_children", []):
                if col.get("type") != "column":
                    continue
                name = ""
                tasks: list[Task] = []
                for cb in col.get("_children", []):
                    ct = cb.get("type", "")
                    if ct.startswith("heading") and not name:
                        name = _block_text(cb)
                    elif ct == "to_do":
                        tasks.append(
                            Task(text=_block_text(cb),
                                 checked=bool(cb.get("to_do", {}).get("checked", False)))
                        )
                days.append(Day(name=name, tasks=tasks))
    return Week(label=label, days=days, goals=goals)


def _clean_rich_text(rich_text: list[dict] | None) -> list[dict]:
    """Rebuild rich_text for a create payload: keep text runs + annotations;
    degrade mentions / custom emoji to a plain text run from their plain_text."""
    out: list[dict] = []
    for rt in rich_text or []:
        annotations = rt.get("annotations")
        if rt.get("type") == "text":
            content = rt.get("text", {}).get("content", "")
            item: dict = {"type": "text", "text": {"content": content}}
            link = rt.get("text", {}).get("link")
            if link:
                item["text"]["link"] = link
            if annotations:
                item["annotations"] = annotations
            out.append(item)
        else:
            content = rt.get("plain_text", "")
            if not content:
                continue
            item = {"type": "text", "text": {"content": content}}
            if annotations:
                item["annotations"] = annotations
            out.append(item)
    return out


# Notion accepts at most 2 levels of nested children and 100 blocks per array in
# a single create request. The template (page → column_list → column → to_do) sits
# exactly at the 2-level ceiling; anything deeper (e.g. a to_do sub-task) is dropped
# with a warning rather than sent and rejecting the whole POST.
_MAX_CREATE_DEPTH = 2
_MAX_CHILDREN_PER_ARRAY = 100


def _transform_block(b: dict, depth: int = 0) -> dict | None:
    """Turn a fetched block into a create payload: strip read-only fields, reset
    to_do checkboxes, recurse into nested children up to Notion's 2-level limit."""
    t = b.get("type", "")
    if t not in CREATABLE_TYPES:
        logger.info("Notion clone: skipping uncreatable block type %r", t)
        return None
    src = b.get(t, {}) or {}
    content: dict = {}
    if "rich_text" in src:
        content["rich_text"] = _clean_rich_text(src.get("rich_text"))
    if "color" in src:
        content["color"] = src["color"]
    if t == "to_do":
        content["checked"] = False  # a clone always starts unchecked
    if t == "code":
        content["language"] = src.get("language", "plain text")
    if t == "callout" and src.get("icon"):
        content["icon"] = src["icon"]
    kids = b.get("_children")
    if kids:
        if depth < _MAX_CREATE_DEPTH:
            content["children"] = to_create_blocks(kids, depth + 1)
        else:
            logger.warning(
                "Notion clone: dropping children of %r beyond Notion's %d-level create limit",
                t, _MAX_CREATE_DEPTH,
            )
    return {"object": "block", "type": t, t: content}


def to_create_blocks(blocks: list[dict], depth: int = 0) -> list[dict]:
    out: list[dict] = []
    for b in blocks:
        new = _transform_block(b, depth)
        if new is not None:
            out.append(new)
    if len(out) > _MAX_CHILDREN_PER_ARRAY:
        logger.warning(
            "Notion clone: %d blocks in one children array exceeds Notion's %d-per-request limit; "
            "the create may be rejected", len(out), _MAX_CHILDREN_PER_ARRAY,
        )
    return out


def _text_block(block_type: str, content: str) -> dict:
    """A create-shaped block carrying a single plain-text rich_text run."""
    return {
        "object": "block",
        "type": block_type,
        block_type: {"rich_text": [{"type": "text", "text": {"content": content}}]},
    }


def _split_paragraphs(text: str) -> list[str]:
    """One paragraph per non-empty line, each hard-chunked to Notion's char cap.
    Splitting per line (not per blank-line block) keeps the review readable even
    when the model emits no blank separators between its labeled sections."""
    out: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        for i in range(0, len(line), _MAX_PARAGRAPH_CHARS):
            out.append(line[i:i + _MAX_PARAGRAPH_CHARS])
    return out


def build_review_blocks(label: str, review_text: str) -> list[dict]:
    """Blocks appended onto a reviewed week's page: a divider, the marker heading,
    then the review text as paragraphs. The heading is built from REVIEW_MARKER so
    the visible header and the idempotency marker can never drift apart."""
    blocks: list[dict] = [
        {"object": "block", "type": "divider", "divider": {}},
        _text_block("heading_2", f"{REVIEW_MARKER} — {label}"),
    ]
    blocks.extend(_text_block("paragraph", p) for p in _split_paragraphs(review_text))
    return blocks


def _has_review_marker(children: list[dict]) -> bool:
    """True when a review has already been written back — a heading_2 whose text
    starts with REVIEW_MARKER (label-independent, so it matches on any week)."""
    for b in children:
        if b.get("type") == "heading_2" and _block_text(b).startswith(REVIEW_MARKER):
            return True
    return False


def _title_prefix(title: str) -> str:
    """Everything before the last '(' in a week title, preserving spacing."""
    idx = title.rfind("(")
    return title[:idx] if idx != -1 else (title.rstrip() + "  ")


def _next_monday(today: date) -> date:
    """The upcoming Monday (never today, even if today is a Monday)."""
    delta = (7 - today.weekday()) % 7
    return today + timedelta(days=delta or 7)


def _next_week_title(prefix: str, start: date, end: date) -> str:
    # Index _MONTH_NAMES rather than strftime("%B") — %B is locale-dependent and
    # would both corrupt the title and break the English-only re-parse under a
    # non-English server locale.
    return (f"{prefix}({_MONTH_NAMES[start.month - 1]} {start.day} - "
            f"{_MONTH_NAMES[end.month - 1]} {end.day})")


# --------------------------------------------------------------------------- #
# Network layer
# --------------------------------------------------------------------------- #

def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API_BASE,
        headers={
            "Authorization": f"Bearer {config.NOTION_API_KEY}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        timeout=_TIMEOUT,
    )


async def _get_children(client: httpx.AsyncClient, block_id: str) -> list[dict]:
    results: list[dict] = []
    cursor: str | None = None
    while True:
        params: dict = {"page_size": _PAGE_SIZE}
        if cursor:
            params["start_cursor"] = cursor
        r = await client.get(f"/blocks/{block_id}/children", params=params)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            return results
        cursor = data.get("next_cursor")


async def _fetch_block_tree(client: httpx.AsyncClient, block_id: str) -> list[dict]:
    blocks = await _get_children(client, block_id)
    for b in blocks:
        if b.get("has_children"):
            b["_children"] = await _fetch_block_tree(client, b["id"])
    return blocks


async def _get_page(client: httpx.AsyncClient, page_id: str) -> dict:
    r = await client.get(f"/pages/{page_id}")
    r.raise_for_status()
    return r.json()


async def _find_week_page(client: httpx.AsyncClient, today: date, strict: bool = False) -> WeekPage | None:
    children = await _get_children(client, config.NOTION_TODO_PARENT_ID)
    return _select_week_page(children, today, strict=strict)


async def find_current_week_page(today: date) -> WeekPage | None:
    """Locate the week page under the parent that contains `today`. Fails soft."""
    try:
        async with _client() as client:
            return await _find_week_page(client, today)
    except Exception:
        logger.exception("Notion: find_current_week_page failed")
        return None


async def fetch_week(page_id: str) -> Week:
    """Read a week page's full block tree into a Week. Raises on error (caller catches)."""
    async with _client() as client:
        page = await _get_page(client, page_id)
        label = _page_title(page)
        blocks = await _fetch_block_tree(client, page_id)
    return parse_week(blocks, label)


async def create_next_week(today: date, source_page_id: str) -> str | None:
    """Clone the source page (current week by default) into next week's page under
    the parent. Returns the new page id, or None if next week's page already exists.
    Raises on error (caller catches)."""
    start = _next_monday(today)
    end = start + timedelta(days=6)
    source_id = config.NOTION_TEMPLATE_PAGE_ID or source_page_id
    async with _client() as client:
        # strict: only skip if a page actually covers next week — the lenient
        # fallback would return this week's page and block every create.
        if await _find_week_page(client, start, strict=True) is not None:
            logger.info("Notion: next week's page already exists; skipping create")
            return None
        page = await _get_page(client, source_id)
        title = _next_week_title(_title_prefix(_page_title(page)), start, end)
        blocks = await _fetch_block_tree(client, source_id)
        payload: dict = {
            "parent": {"page_id": config.NOTION_TODO_PARENT_ID},
            "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
            "children": to_create_blocks(blocks),
        }
        icon = page.get("icon")
        if icon:
            payload["icon"] = icon
        r = await client.post("/pages", json=payload)
        r.raise_for_status()
        new_id = r.json().get("id")
    logger.info("Notion: created next week's page %s (%s)", new_id, title)
    return new_id


async def _append_children(client: httpx.AsyncClient, block_id: str, blocks: list[dict]) -> None:
    r = await client.patch(f"/blocks/{block_id}/children", json={"children": blocks})
    r.raise_for_status()


async def append_review(page_id: str, label: str, review_text: str) -> bool:
    """Append the weekly review onto its week page, once. Returns True when written,
    False when a review is already present (skip-once). Raises on network error —
    the caller catches; the review is already delivered to Telegram regardless."""
    async with _client() as client:
        children = await _get_children(client, page_id)
        if _has_review_marker(children):
            logger.info("Notion: review already on %s; skipping write-back", page_id)
            return False
        await _append_children(client, page_id, build_review_blocks(label, review_text))
    logger.info("Notion: wrote weekly review back to %s", page_id)
    return True
