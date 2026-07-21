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
# create_next_week — network mocked
# --------------------------------------------------------------------------- #

class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class _FakeClient:
    """Minimal async-context httpx stand-in for create_next_week."""

    def __init__(self, page: dict, tree: list[dict]):
        self._page = page
        self._tree = tree
        self.post_payload: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        if url.startswith("/pages/"):
            return _FakeResp(self._page)
        if "/children" in url:
            return _FakeResp({"results": self._tree, "has_more": False})
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url, json=None):
        self.post_payload = json
        return _FakeResp({"id": "new-page-id"})


async def test_create_next_week_idempotent_skips_when_exists(monkeypatch):
    fake = _FakeClient(page={}, tree=[])

    async def _existing(client, day):
        return WeekPage(id="already", title="Weekly (July 27 - August 2)")

    monkeypatch.setattr(notion, "_client", lambda: fake)
    monkeypatch.setattr(notion, "_find_week_page", _existing)
    result = await notion.create_next_week(date(2026, 7, 26), source_page_id="src")
    assert result is None
    assert fake.post_payload is None  # no page created


async def test_create_next_week_posts_reset_clone(monkeypatch):
    page = {
        "icon": {"type": "emoji", "emoji": "👨‍💻"},
        "properties": {"Name": {"type": "title", "title": _rt("Weekly To-do List  (July 20 - July 26)")}},
    }
    tree = [_todo("🏃 Running", True)]  # flat: no has_children → no recursion
    fake = _FakeClient(page=page, tree=tree)

    async def _none(client, day):
        return None

    monkeypatch.setattr(notion, "_client", lambda: fake)
    monkeypatch.setattr(notion, "_find_week_page", _none)
    monkeypatch.setattr(config, "NOTION_TODO_PARENT_ID", "parent-id")
    monkeypatch.setattr(config, "NOTION_TEMPLATE_PAGE_ID", "")

    result = await notion.create_next_week(date(2026, 7, 26), source_page_id="src")

    assert result == "new-page-id"
    payload = fake.post_payload
    assert payload["parent"] == {"page_id": "parent-id"}
    title = payload["properties"]["title"]["title"][0]["text"]["content"]
    assert title == "Weekly To-do List  (July 27 - August 2)"
    assert payload["icon"] == {"type": "emoji", "emoji": "👨‍💻"}
    assert payload["children"][0]["to_do"]["checked"] is False  # reset on clone
