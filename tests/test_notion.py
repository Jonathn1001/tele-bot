import os

# Must be set before any project module is imported (config reads env at import).
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from datetime import date
from unittest.mock import patch

import config
import notion
from notion import Day, Task, WeekPage


# --------------------------------------------------------------------------- #
# Block fixture builders
# --------------------------------------------------------------------------- #

def _rt(text: str) -> list[dict]:
    return [{"type": "text", "plain_text": text, "text": {"content": text}}]


def _todo(text: str, checked: bool, **extra) -> dict:
    block = {"type": "to_do", "to_do": {"rich_text": _rt(text), "checked": checked}}
    block.update(extra)
    return block


def _heading(text: str) -> dict:
    return {"type": "heading_2", "heading_2": {"rich_text": _rt(text)}}


def _bullet(text: str) -> dict:
    return {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _rt(text)}}


def _column(children: list[dict]) -> dict:
    return {"type": "column", "column": {}, "_children": children}


def _column_list(cols: list[dict]) -> dict:
    return {"type": "column_list", "column_list": {}, "_children": cols}


def _child_page(pid: str, title: str, created: str) -> dict:
    return {"type": "child_page", "id": pid, "created_time": created, "child_page": {"title": title}}


# --------------------------------------------------------------------------- #
# parse_title_range
# --------------------------------------------------------------------------- #

def test_parse_title_range_in_range():
    r = notion.parse_title_range("👨‍💻 Weekly To-do List  (July 20 - July 26)", date(2026, 7, 21))
    assert r == (date(2026, 7, 20), date(2026, 7, 26))


def test_parse_title_range_cross_month():
    r = notion.parse_title_range("Weekly To-do List (July 27 - August 2)", date(2026, 7, 28))
    assert r == (date(2026, 7, 27), date(2026, 8, 2))


def test_parse_title_range_cross_year():
    r = notion.parse_title_range("Weekly (Dec 29 - Jan 4)", date(2026, 12, 30))
    assert r == (date(2026, 12, 29), date(2027, 1, 4))


def test_parse_title_range_abbreviations():
    r = notion.parse_title_range("Weekly (Aug 3 - Aug 9)", date(2026, 8, 4))
    assert r == (date(2026, 8, 3), date(2026, 8, 9))


def test_parse_title_range_no_range_returns_none():
    assert notion.parse_title_range("Weekly To-do List Template", date(2026, 7, 21)) is None


# --------------------------------------------------------------------------- #
# _select_week_page
# --------------------------------------------------------------------------- #

def test_select_picks_page_containing_today():
    children = [
        _child_page("a", "Weekly (July 13 - July 19)", "2026-07-12"),
        _child_page("b", "Weekly (July 20 - July 26)", "2026-07-19"),
    ]
    got = notion._select_week_page(children, date(2026, 7, 21))
    assert got is not None and got.id == "b"


def test_select_ignores_non_child_page_blocks():
    children = [
        {"type": "paragraph", "id": "p", "paragraph": {}},
        _child_page("b", "Weekly (July 20 - July 26)", "2026-07-19"),
    ]
    got = notion._select_week_page(children, date(2026, 7, 21))
    assert got is not None and got.id == "b"


def test_select_falls_back_to_newest_by_created_time():
    # Neither range contains today; document order puts the older page last.
    children = [
        _child_page("new", "Weekly (July 6 - July 12)", "2026-07-05"),
        _child_page("old", "Weekly (June 29 - July 5)", "2026-06-28"),
    ]
    got = notion._select_week_page(children, date(2026, 8, 1))
    assert got is not None and got.id == "new"  # newest created_time, not last in list


def test_select_empty_returns_none():
    assert notion._select_week_page([], date(2026, 7, 21)) is None


def test_select_strict_returns_none_when_nothing_contains_date():
    # Regression: the create idempotency guard must NOT fall back to newest,
    # or it mistakes this week's page for next week's and never creates.
    children = [_child_page("cur", "Weekly (July 20 - July 26)", "2026-07-19")]
    assert notion._select_week_page(children, date(2026, 7, 27), strict=True) is None
    # Non-strict still falls back to the newest candidate.
    assert notion._select_week_page(children, date(2026, 7, 27), strict=False).id == "cur"


# --------------------------------------------------------------------------- #
# parse_week
# --------------------------------------------------------------------------- #

def test_parse_week_extracts_days_tasks_goals():
    blocks = [
        _bullet("🏃 Wake up at 5:30"),
        _column_list([
            _column([_heading("Monday"), _todo("🏃 Running", False), _todo("🔥 Chest", True)]),
            _column([_heading("Tuesday"), _todo("🏃 Running", True)]),
        ]),
    ]
    week = notion.parse_week(blocks, "My Week")
    assert week.label == "My Week"
    assert week.goals == ["🏃 Wake up at 5:30"]
    assert week.days[0].name == "Monday"
    assert week.days[0].tasks == [Task("🏃 Running", False), Task("🔥 Chest", True)]
    assert week.days[1].name == "Tuesday"
    assert week.days[1].tasks == [Task("🏃 Running", True)]


# --------------------------------------------------------------------------- #
# to_create_blocks
# --------------------------------------------------------------------------- #

def test_to_create_strips_readonly_and_resets_checked():
    src = _todo("Task", True, id="abc", created_time="t", has_children=False)
    src["to_do"]["annotations"] = {"bold": True, "color": "red"}
    src["to_do"]["color"] = "default"
    out = notion.to_create_blocks([src])
    assert len(out) == 1
    block = out[0]
    assert "id" not in block and "created_time" not in block and "has_children" not in block
    assert block["type"] == "to_do"
    assert block["to_do"]["checked"] is False
    assert block["to_do"]["color"] == "default"
    assert block["to_do"]["rich_text"][0]["text"]["content"] == "Task"


def test_to_create_degrades_custom_emoji_mention_to_text():
    src = {
        "type": "to_do",
        "to_do": {
            "rich_text": [{"type": "mention", "plain_text": ":programming: Working",
                           "mention": {"type": "custom_emoji"}}],
            "checked": False,
        },
    }
    out = notion.to_create_blocks([src])
    rt = out[0]["to_do"]["rich_text"][0]
    assert rt["type"] == "text"
    assert rt["text"]["content"] == ":programming: Working"


def test_to_create_skips_uncreatable_block_type():
    src = {"type": "table_of_contents", "table_of_contents": {}}
    assert notion.to_create_blocks([src]) == []


def test_to_create_recurses_into_columns():
    tree = [_column_list([_column([_todo("🏃 Running", True)])])]
    out = notion.to_create_blocks(tree)
    cl = out[0]
    assert cl["type"] == "column_list"
    col = cl["column_list"]["children"][0]
    assert col["type"] == "column"
    todo = col["column"]["children"][0]
    assert todo["type"] == "to_do" and todo["to_do"]["checked"] is False


def test_to_create_drops_children_beyond_two_levels():
    # column_list(0) -> column(1) -> to_do(2) -> sub to_do(3): the 3rd nesting
    # level exceeds Notion's create limit and must be dropped, not sent (which
    # would make Notion reject the entire POST).
    parent_todo = {"type": "to_do", "to_do": {"rich_text": _rt("parent"), "checked": True},
                   "_children": [_todo("sub-task", True)]}
    tree = [_column_list([_column([parent_todo])])]
    out = notion.to_create_blocks(tree)
    todo = out[0]["column_list"]["children"][0]["column"]["children"][0]
    assert todo["type"] == "to_do"
    assert "children" not in todo["to_do"]  # 3rd-level children dropped


# --------------------------------------------------------------------------- #
# title / date helpers
# --------------------------------------------------------------------------- #

def test_next_monday_from_sunday():
    assert notion._next_monday(date(2026, 7, 26)) == date(2026, 7, 27)  # Sun → next day


def test_next_monday_from_monday_rolls_a_full_week():
    assert notion._next_monday(date(2026, 7, 27)) == date(2026, 8, 3)  # Mon → next Mon


def test_title_prefix_and_next_week_title():
    prefix = notion._title_prefix("Weekly To-do List  (July 20 - July 26)")
    assert prefix == "Weekly To-do List  "
    title = notion._next_week_title(prefix, date(2026, 7, 27), date(2026, 8, 2))
    assert title == "Weekly To-do List  (July 27 - August 2)"


# --------------------------------------------------------------------------- #
# create_next_week — network mocked (drives the REAL idempotency guard, not a
# stubbed _find_week_page, so the strict-guard regression stays covered)
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    """Async-context httpx stand-in: serves the parent's children (idempotency
    guard) and the source page + its block tree (the clone)."""

    def __init__(self, parent_children, source_page, source_tree,
                 parent_id="parent-id", source_id="src"):
        self.parent_children = parent_children
        self.source_page = source_page
        self.source_tree = source_tree
        self.parent_id = parent_id
        self.source_id = source_id
        self.post_payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        if url == f"/blocks/{self.parent_id}/children":
            return _FakeResp({"results": self.parent_children, "has_more": False})
        if url == f"/pages/{self.source_id}":
            return _FakeResp(self.source_page)
        if url == f"/blocks/{self.source_id}/children":
            return _FakeResp({"results": self.source_tree, "has_more": False})
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url, json=None):
        self.post_payload = json
        return _FakeResp({"id": "new-page-id"})


def _source_page() -> dict:
    return {
        "icon": {"type": "emoji", "emoji": "\U0001f469‍\U0001f4bb"},
        "properties": {"Name": {"type": "title",
                                "title": _rt("Weekly To-do List  (July 20 - July 26)")}},
    }


async def test_create_next_week_idempotent_skips_when_next_week_exists(monkeypatch):
    # Parent already has next week's page → strict guard finds it → skip.
    fake = _FakeClient(
        parent_children=[
            _child_page("cur", "Weekly (July 20 - July 26)", "2026-07-19"),
            _child_page("nxt", "Weekly (July 27 - August 2)", "2026-07-26"),
        ],
        source_page=_source_page(),
        source_tree=[_todo("Running", True)],
    )
    monkeypatch.setattr(notion, "_client", lambda: fake)
    monkeypatch.setattr(config, "NOTION_TODO_PARENT_ID", "parent-id")
    monkeypatch.setattr(config, "NOTION_TEMPLATE_PAGE_ID", "")
    result = await notion.create_next_week(date(2026, 7, 26), source_page_id="src")
    assert result is None
    assert fake.post_payload is None  # no page created


async def test_create_next_week_posts_when_only_this_week_exists(monkeypatch):
    # Regression: only this week exists → strict guard returns None → create
    # proceeds and POSTs a reset clone. The fallback bug returned this week's
    # page here and skipped forever.
    fake = _FakeClient(
        parent_children=[_child_page("cur", "Weekly (July 20 - July 26)", "2026-07-19")],
        source_page=_source_page(),
        source_tree=[_todo("Running", True)],  # flat: no recursion
    )
    monkeypatch.setattr(notion, "_client", lambda: fake)
    monkeypatch.setattr(config, "NOTION_TODO_PARENT_ID", "parent-id")
    monkeypatch.setattr(config, "NOTION_TEMPLATE_PAGE_ID", "")

    result = await notion.create_next_week(date(2026, 7, 26), source_page_id="src")

    assert result == "new-page-id"
    _assert_reset_clone(fake.post_payload)


def _assert_reset_clone(payload: dict) -> None:
    assert payload is not None
    assert payload["parent"] == {"page_id": "parent-id"}
    title = payload["properties"]["title"]["title"][0]["text"]["content"]
    assert title == "Weekly To-do List  (July 27 - August 2)"
    assert payload["icon"]["type"] == "emoji"
    assert payload["children"][0]["to_do"]["checked"] is False  # reset on clone


# --------------------------------------------------------------------------- #
# build_review_blocks (pure)
# --------------------------------------------------------------------------- #

def _para_texts(blocks: list[dict]) -> list[str]:
    return [b["paragraph"]["rich_text"][0]["text"]["content"]
            for b in blocks if b["type"] == "paragraph"]


def test_build_review_blocks_divider_heading_paragraphs():
    label = "Weekly To-do List  (July 20 - July 26)"
    text = "Recap: 12/20 done.\nInsights: gym strong.\n\nNext Week: read more.\nOne-liner: go."
    blocks = notion.build_review_blocks(label, text)

    assert all(b["object"] == "block" for b in blocks)          # full create shape
    assert blocks[0]["type"] == "divider"
    assert blocks[1]["type"] == "heading_2"
    heading = blocks[1]["heading_2"]["rich_text"][0]["text"]["content"]
    assert heading == f"{notion.REVIEW_MARKER} — {label}"       # built from the constant
    # one paragraph per non-empty line; the blank line is dropped
    assert _para_texts(blocks) == [
        "Recap: 12/20 done.", "Insights: gym strong.",
        "Next Week: read more.", "One-liner: go.",
    ]


def test_build_review_blocks_hard_chunks_long_line():
    long = "x" * 4000  # > 1900-char Notion rich_text cap → must split
    blocks = notion.build_review_blocks("L", long)
    paras = _para_texts(blocks)
    assert len(paras) == 3                                       # ceil(4000 / 1900)
    assert all(len(p) <= 1900 for p in paras)
    assert "".join(paras) == long                               # no data lost


def test_build_review_blocks_empty_text_has_no_paragraphs():
    blocks = notion.build_review_blocks("L", "\n  \n")
    assert [b["type"] for b in blocks] == ["divider", "heading_2"]


# --------------------------------------------------------------------------- #
# _has_review_marker (pure)
# --------------------------------------------------------------------------- #

def test_has_review_marker_true_for_matching_heading_2():
    children = [_heading(f"{notion.REVIEW_MARKER} — Weekly (July 20 - July 26)")]
    assert notion._has_review_marker(children) is True


def test_has_review_marker_ignores_other_block_types():
    marker_text = f"{notion.REVIEW_MARKER} — X"
    h1 = {"type": "heading_1", "heading_1": {"rich_text": _rt(marker_text)}}
    para = {"type": "paragraph", "paragraph": {"rich_text": _rt(marker_text)}}
    assert notion._has_review_marker([h1, para]) is False       # only heading_2 counts


def test_has_review_marker_false_when_absent():
    assert notion._has_review_marker([_heading("Monday"), _todo("Task", False)]) is False


# --------------------------------------------------------------------------- #
# append_review — network mocked
# --------------------------------------------------------------------------- #

class _FakeAppendClient:
    """Async-context httpx stand-in for append_review: serves the page's direct
    children (marker scan) and captures the PATCH payload."""

    def __init__(self, children, page_id="pg", get_error=None):
        self.children = children
        self.page_id = page_id
        self.get_error = get_error
        self.patch_url: str | None = None
        self.patch_payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        if self.get_error is not None:
            raise self.get_error
        if url == f"/blocks/{self.page_id}/children":
            return _FakeResp({"results": self.children, "has_more": False})
        raise AssertionError(f"unexpected GET {url}")

    async def patch(self, url, json=None):
        self.patch_url = url
        self.patch_payload = json
        return _FakeResp({})


async def test_append_review_writes_when_no_marker(monkeypatch):
    fake = _FakeAppendClient(children=[_heading("Monday")])
    monkeypatch.setattr(notion, "_client", lambda: fake)
    result = await notion.append_review("pg", "My Week", "Recap: ok.")
    assert result is True
    assert fake.patch_url == "/blocks/pg/children"
    assert fake.patch_payload["children"] == notion.build_review_blocks("My Week", "Recap: ok.")


async def test_append_review_skips_when_marker_present(monkeypatch):
    fake = _FakeAppendClient(children=[_heading(f"{notion.REVIEW_MARKER} — My Week")])
    monkeypatch.setattr(notion, "_client", lambda: fake)
    result = await notion.append_review("pg", "My Week", "Recap: ok.")
    assert result is False
    assert fake.patch_payload is None                           # no write issued


async def test_append_review_propagates_network_error(monkeypatch):
    fake = _FakeAppendClient(children=[], get_error=RuntimeError("boom"))
    monkeypatch.setattr(notion, "_client", lambda: fake)
    try:
        await notion.append_review("pg", "My Week", "Recap: ok.")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError to propagate to the caller")
