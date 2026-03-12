import os

# Must be set before any project module is imported (config.py reads these at import time)
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

import bot
from buffer import Message, MessageBuffer


def _make_buffer(*texts: str) -> MessageBuffer:
    buf = MessageBuffer()
    for t in texts:
        buf.add("@ch", Message(channel="@ch", text=t, date=datetime.now()))
    return buf


def _mock_msg() -> AsyncMock:
    m = AsyncMock()
    m.answer = AsyncMock()
    return m


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

async def test_start_replies_once():
    msg = _mock_msg()
    await bot.cmd_start(msg)
    msg.answer.assert_called_once()


async def test_start_contains_bot_name():
    msg = _mock_msg()
    await bot.cmd_start(msg)
    text = msg.answer.call_args[0][0]
    assert "Telegram Intel Bot" in text


# ---------------------------------------------------------------------------
# /channels
# ---------------------------------------------------------------------------

async def test_channels_empty_buffer():
    msg = _mock_msg()
    with patch.object(bot, "_buffer", None):
        await bot.cmd_channels(msg)
    msg.answer.assert_called_once_with("No messages collected yet.")


async def test_channels_populated_buffer():
    msg = _mock_msg()
    buf = _make_buffer("hello", "world")
    with patch.object(bot, "_buffer", buf):
        await bot.cmd_channels(msg)
    text = msg.answer.call_args[0][0]
    assert "@ch" in text
    assert "2" in text


# ---------------------------------------------------------------------------
# Analysis commands — empty buffer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd_fn", [
    bot.cmd_summary,
    bot.cmd_threat,
])
async def test_analysis_empty_buffer(cmd_fn):
    msg = _mock_msg()
    with patch.object(bot, "_buffer", None):
        await cmd_fn(msg)
    msg.answer.assert_called_once_with("No messages collected yet. Please wait a moment.")


# ---------------------------------------------------------------------------
# Analysis commands — populated buffer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd_fn,analyzer_fn", [
    (bot.cmd_summary,   "summarize"),
    (bot.cmd_threat,    "assess_threat"),
])
async def test_analysis_sends_analyzing_first(cmd_fn, analyzer_fn):
    msg = _mock_msg()
    buf = _make_buffer("test message")
    with patch.object(bot, "_buffer", buf), \
         patch(f"analyzer.{analyzer_fn}", new=AsyncMock(return_value="mocked result")):
        await cmd_fn(msg)
    first_call_text = msg.answer.call_args_list[0][0][0]
    assert first_call_text == "Analyzing..."


@pytest.mark.parametrize("cmd_fn,analyzer_fn", [
    (bot.cmd_summary,   "summarize"),
    (bot.cmd_threat,    "assess_threat"),
])
async def test_analysis_calls_analyzer_and_replies(cmd_fn, analyzer_fn):
    msg = _mock_msg()
    buf = _make_buffer("test message")
    mock_fn = AsyncMock(return_value="mocked result")
    with patch.object(bot, "_buffer", buf), \
         patch(f"analyzer.{analyzer_fn}", new=mock_fn):
        await cmd_fn(msg)
    mock_fn.assert_called_once()
    all_texts = [c[0][0] for c in msg.answer.call_args_list]
    assert any("mocked result" in t for t in all_texts)


# ---------------------------------------------------------------------------
# /factcheck
# ---------------------------------------------------------------------------

async def test_factcheck_no_claim_returns_usage():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = None
    buf = _make_buffer("some message")
    with patch.object(bot, "_buffer", buf):
        await bot.cmd_factcheck(msg, cmd)
    msg.answer.assert_called_once_with("Usage: /factcheck <your claim>")


async def test_factcheck_claim_too_long_returns_error():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "x" * 501
    buf = _make_buffer("some message")
    with patch.object(bot, "_buffer", buf):
        await bot.cmd_factcheck(msg, cmd)
    text = msg.answer.call_args[0][0]
    assert "too long" in text.lower()


async def test_factcheck_empty_buffer_returns_no_messages():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "Russia attacked Ukraine"
    with patch.object(bot, "_buffer", None):
        await bot.cmd_factcheck(msg, cmd)
    msg.answer.assert_called_once_with("No messages collected yet. Please wait a moment.")


async def test_factcheck_calls_analyzer_and_replies():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "Russia attacked Ukraine"
    buf = _make_buffer("test message")
    mock_fn = AsyncMock(return_value="SUPPORTED\nEvidence.")
    with patch.object(bot, "_buffer", buf), \
         patch("analyzer.fact_check", new=mock_fn):
        await bot.cmd_factcheck(msg, cmd)
    mock_fn.assert_called_once()
    all_texts = [c[0][0] for c in msg.answer.call_args_list]
    assert any("SUPPORTED" in t for t in all_texts)
