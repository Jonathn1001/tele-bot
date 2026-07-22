import os

# Must be set before any project module is imported (config reads env at import).
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import analyzer
import config
import main
import notion

VN = ZoneInfo("Asia/Ho_Chi_Minh")
SUNDAY = datetime(2026, 7, 26, 19, 0, tzinfo=VN)     # July 26 2026 is a Sunday
SATURDAY = datetime(2026, 7, 25, 19, 0, tzinfo=VN)   # not Sunday


def _owner_texts(sent: AsyncMock) -> str:
    # send_to_owner(bot, text) — join every text sent.
    return " ".join(c.args[1] for c in sent.await_args_list)


async def test_non_sunday_noops(monkeypatch):
    sent = AsyncMock()
    find = AsyncMock()
    monkeypatch.setattr(main, "send_to_owner", sent)
    monkeypatch.setattr(notion, "find_current_week_page", find)
    await main.run_weekly_review(AsyncMock(), now=SATURDAY)
    find.assert_not_awaited()
    sent.assert_not_awaited()


async def test_review_failure_still_runs_create(monkeypatch):
    # fetch_week raising must NOT skip the clone (it re-reads the source page)
    # and the owner must still get a message — the isolation contract.
    page = notion.WeekPage(id="p1", title="Weekly To-do List  (July 20 - July 26)")
    sent = AsyncMock()
    create = AsyncMock(return_value="new-id")
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", True)
    monkeypatch.setattr(main, "send_to_owner", sent)
    monkeypatch.setattr(notion, "find_current_week_page", AsyncMock(return_value=page))
    monkeypatch.setattr(notion, "fetch_week", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(notion, "create_next_week", create)

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)

    create.assert_awaited_once()                      # clone ran despite review failure
    texts = _owner_texts(sent).lower()
    assert "review failed" in texts                   # owner told about the failure
    assert "next week" in texts                       # and about the successful clone


async def test_happy_path_reviews_then_creates(monkeypatch):
    page = notion.WeekPage(id="p1", title="Weekly To-do List  (July 20 - July 26)")
    week = notion.Week(label="Weekly To-do List  (July 20 - July 26)", days=[], goals=[])
    sent = AsyncMock()
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", True)
    monkeypatch.setattr(main, "send_to_owner", sent)
    monkeypatch.setattr(notion, "find_current_week_page", AsyncMock(return_value=page))
    monkeypatch.setattr(notion, "fetch_week", AsyncMock(return_value=week))
    monkeypatch.setattr(analyzer, "weekly_review", AsyncMock(return_value="Recap ..."))
    monkeypatch.setattr(notion, "create_next_week", AsyncMock(return_value="new-id"))

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)

    texts = _owner_texts(sent)
    assert "Weekly Review" in texts and "Recap ..." in texts
    assert "Next week" in texts


async def test_create_failure_does_not_lose_review(monkeypatch):
    page = notion.WeekPage(id="p1", title="Weekly To-do List  (July 20 - July 26)")
    week = notion.Week(label="W", days=[], goals=[])
    sent = AsyncMock()
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", True)
    monkeypatch.setattr(main, "send_to_owner", sent)
    monkeypatch.setattr(notion, "find_current_week_page", AsyncMock(return_value=page))
    monkeypatch.setattr(notion, "fetch_week", AsyncMock(return_value=week))
    monkeypatch.setattr(analyzer, "weekly_review", AsyncMock(return_value="Recap"))
    monkeypatch.setattr(notion, "create_next_week", AsyncMock(side_effect=RuntimeError("boom")))

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)

    texts = _owner_texts(sent)
    assert "Weekly Review" in texts                   # review still delivered
    assert "Couldn't create" in texts                 # create failure reported, not swallowed


# --------------------------------------------------------------------------- #
# Write-back to Notion (Sunday-job only, skip-once, isolated)
# --------------------------------------------------------------------------- #

def _wire_review(monkeypatch, review_text="Recap: good."):
    """Common happy-path stubs; returns the page used so callers can assert ids."""
    page = notion.WeekPage(id="p1", title="Weekly To-do List  (July 20 - July 26)")
    week = notion.Week(label="Weekly To-do List  (July 20 - July 26)", days=[], goals=[])
    monkeypatch.setattr(main, "send_to_owner", AsyncMock())
    monkeypatch.setattr(notion, "find_current_week_page", AsyncMock(return_value=page))
    monkeypatch.setattr(notion, "fetch_week", AsyncMock(return_value=week))
    monkeypatch.setattr(analyzer, "weekly_review", AsyncMock(return_value=review_text))
    monkeypatch.setattr(notion, "create_next_week", AsyncMock(return_value="new-id"))
    return page, week


async def test_writeback_called_on_successful_review(monkeypatch):
    page, week = _wire_review(monkeypatch)
    append = AsyncMock(return_value=True)
    monkeypatch.setattr(notion, "append_review", append)
    monkeypatch.setattr(config, "WRITEBACK_ENABLED", True)
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", True)

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)

    append.assert_awaited_once_with(page.id, week.label, "Recap: good.")


async def test_writeback_failure_keeps_review_and_clone(monkeypatch):
    page, _ = _wire_review(monkeypatch)
    create = notion.create_next_week  # AsyncMock from _wire_review
    monkeypatch.setattr(notion, "append_review", AsyncMock(side_effect=RuntimeError("boom")))
    monkeypatch.setattr(config, "WRITEBACK_ENABLED", True)
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", True)

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)  # must not raise

    texts = _owner_texts(main.send_to_owner)
    assert "Weekly Review" in texts and "Recap: good." in texts  # review delivered
    create.assert_awaited_once()                                 # clone still ran


async def test_writeback_skipped_when_disabled(monkeypatch):
    _wire_review(monkeypatch)
    append = AsyncMock()
    monkeypatch.setattr(notion, "append_review", append)
    monkeypatch.setattr(config, "WRITEBACK_ENABLED", False)
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", False)

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)

    append.assert_not_awaited()


async def test_writeback_skipped_for_placeholder_text(monkeypatch):
    _wire_review(monkeypatch, review_text=analyzer.NO_TASKS_REPLY)
    append = AsyncMock()
    monkeypatch.setattr(notion, "append_review", append)
    monkeypatch.setattr(config, "WRITEBACK_ENABLED", True)
    monkeypatch.setattr(config, "AUTOCREATE_ENABLED", False)

    await main.run_weekly_review(AsyncMock(), now=SUNDAY)

    append.assert_not_awaited()                                  # don't persist the placeholder
