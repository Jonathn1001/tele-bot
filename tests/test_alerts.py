import os

# config.py reads these at import time
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

import time
from datetime import datetime

import pytest
from unittest.mock import AsyncMock

import health
from alerts import AlertMatcher


# ---------------------------------------------------------------------------
# AlertMatcher
# ---------------------------------------------------------------------------

def test_matcher_case_insensitive():
    m = AlertMatcher(["nuclear", "invasion"])
    assert m.match("NUCLEAR test detected") == ["nuclear"]


def test_matcher_multiple_hits_in_watchlist_order():
    m = AlertMatcher(["nuclear", "invasion", "ceasefire"])
    # Text mentions them out of order; result follows watchlist order.
    assert m.match("ceasefire broken, invasion imminent") == ["invasion", "ceasefire"]


def test_matcher_dedupes_repeated_keyword():
    m = AlertMatcher(["strike"])
    assert m.match("strike, another strike, third strike") == ["strike"]


def test_matcher_word_boundary_no_substring_false_positive():
    m = AlertMatcher(["strike"])
    assert m.match("he struck out at the strikeout zone") == []


def test_matcher_multiword_phrase():
    m = AlertMatcher(["martial law"])
    assert m.match("government declared martial law today") == ["martial law"]


def test_matcher_hyphen_boundary_matches():
    m = AlertMatcher(["airstrike"])
    assert m.match("an air-strike... airstrike confirmed") == ["airstrike"]


def test_matcher_empty_watchlist_disabled():
    m = AlertMatcher([])
    assert not m.enabled
    assert m.match("nuclear invasion ceasefire") == []


def test_matcher_ignores_blank_keywords():
    m = AlertMatcher(["", "  ", "nuclear"])
    assert m.enabled
    assert m.match("nuclear") == ["nuclear"]


def test_matcher_no_match_returns_empty():
    m = AlertMatcher(["nuclear"])
    assert m.match("quiet day on the front") == []


# ---------------------------------------------------------------------------
# health heartbeat / freshness
# ---------------------------------------------------------------------------

def test_touch_and_is_fresh(tmp_path):
    p = str(tmp_path / "hb")
    health.touch(p)
    assert health.is_fresh(p, max_age=60)


def test_is_fresh_false_when_stale(tmp_path):
    p = str(tmp_path / "hb")
    health.touch(p)
    old = time.time() - 500
    os.utime(p, (old, old))
    assert not health.is_fresh(p, max_age=180)


def test_is_fresh_false_when_missing(tmp_path):
    assert not health.is_fresh(str(tmp_path / "nope"), max_age=180)


# ---------------------------------------------------------------------------
# crawler alert callback (safe wrapper swallows exceptions)
# ---------------------------------------------------------------------------

async def test_safe_alert_swallows_callback_error():
    from crawler import TelegramCrawler
    from buffer import Message
    boom = AsyncMock(side_effect=RuntimeError("send failed"))
    msg = Message(channel="@c", text="nuclear", date=datetime.now())
    # Must not raise even though the callback blows up.
    await TelegramCrawler._safe_alert(boom, msg, ["nuclear"])
    boom.assert_awaited_once()
