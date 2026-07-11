import os

# Must be set before any project module is imported (config.py reads these at import time)
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

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


def _mock_state(current: str | None = None) -> AsyncMock:
    st = AsyncMock()
    st.get_state = AsyncMock(return_value=current)
    return st


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


async def test_start_attaches_quick_keyboard():
    msg = _mock_msg()
    await bot.cmd_start(msg)
    kb = msg.answer.call_args[1]["reply_markup"]
    assert kb is bot.QUICK_KEYBOARD


def test_quick_keyboard_layout():
    kb = bot.QUICK_KEYBOARD
    assert kb.is_persistent is True
    assert kb.resize_keyboard is True
    texts = [b.text for row in kb.keyboard for b in row]
    assert texts == [
        "/summary", "/threat",
        "/hn", "/paper",
        "/factcheck", "/thread",
        "/channels",
    ]


async def test_setup_bot_commands_registers_menu():
    tg_bot = AsyncMock()
    await bot.setup_bot_commands(tg_bot)
    tg_bot.set_my_commands.assert_called_once()
    commands = tg_bot.set_my_commands.call_args[0][0]
    names = [c.command for c in commands]
    assert names == [
        "summary", "threat", "factcheck", "hn",
        "paper", "thread", "channels", "cancel",
    ]


# ---------------------------------------------------------------------------
# /channels
# ---------------------------------------------------------------------------

async def test_channels_empty_buffer():
    msg = _mock_msg()
    with patch.object(bot, "_buffer", None):
        await bot.cmd_channels(msg)
    msg.answer.assert_called_once_with(bot.EMPTY_BUFFER_REPLY)


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
    msg.answer.assert_called_once_with(bot.EMPTY_BUFFER_REPLY)


# ---------------------------------------------------------------------------
# Analysis commands — populated buffer
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd_fn,analyzer_fn", [
    (bot.cmd_summary,   "summarize"),
    (bot.cmd_threat,    "assess_threat"),
])
async def test_analysis_sends_status_first(cmd_fn, analyzer_fn):
    msg = _mock_msg()
    buf = _make_buffer("test message")
    with patch.object(bot, "_buffer", buf), \
         patch(f"analyzer.{analyzer_fn}", new=AsyncMock(return_value="mocked result")):
        await cmd_fn(msg)
    first_call_text = msg.answer.call_args_list[0][0][0]
    # status message tells the user what's happening and mentions message count
    assert "1 message" in first_call_text
    assert "…" in first_call_text


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

async def test_factcheck_no_claim_starts_prompt():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = None
    state = _mock_state()
    await bot.cmd_factcheck(msg, cmd, state)
    state.set_state.assert_called_once_with(bot.PromptFlow.awaiting_claim)
    prompt_text = msg.answer.call_args[0][0]
    assert "claim" in prompt_text
    assert "/cancel" in prompt_text


async def test_factcheck_claim_too_long_returns_error():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "x" * 501
    state = _mock_state()
    buf = _make_buffer("some message")
    with patch.object(bot, "_buffer", buf):
        await bot.cmd_factcheck(msg, cmd, state)
    state.set_state.assert_not_called()
    text = msg.answer.call_args[0][0]
    assert "too long" in text.lower()


async def test_factcheck_empty_buffer_returns_no_messages():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "Russia attacked Ukraine"
    state = _mock_state()
    with patch.object(bot, "_buffer", None):
        await bot.cmd_factcheck(msg, cmd, state)
    state.set_state.assert_not_called()
    msg.answer.assert_called_once_with(bot.EMPTY_BUFFER_REPLY)


async def test_factcheck_calls_analyzer_and_replies():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "Russia attacked Ukraine"
    state = _mock_state()
    buf = _make_buffer("test message")
    mock_fn = AsyncMock(return_value="SUPPORTED\nEvidence.")
    with patch.object(bot, "_buffer", buf), \
         patch("analyzer.fact_check", new=mock_fn):
        await bot.cmd_factcheck(msg, cmd, state)
    state.set_state.assert_not_called()
    mock_fn.assert_called_once()
    all_texts = [c[0][0] for c in msg.answer.call_args_list]
    assert any("SUPPORTED" in t for t in all_texts)


# ---------------------------------------------------------------------------
# Prompt flow — /factcheck via button
# ---------------------------------------------------------------------------

async def test_prompt_claim_runs_factcheck_and_clears_state():
    msg = _mock_msg()
    msg.text = "Russia closed the border"
    state = _mock_state(bot.PromptFlow.awaiting_claim.state)
    buf = _make_buffer("test message")
    mock_fn = AsyncMock(return_value="SUPPORTED\nEvidence.")
    with patch.object(bot, "_buffer", buf), \
         patch("analyzer.fact_check", new=mock_fn):
        await bot.prompt_claim(msg, state)
    state.clear.assert_called_once()
    mock_fn.assert_called_once()
    assert mock_fn.call_args[0][0] == "Russia closed the border"


async def test_prompt_claim_too_long_reprompts_and_keeps_state():
    msg = _mock_msg()
    msg.text = "x" * 501
    state = _mock_state(bot.PromptFlow.awaiting_claim.state)
    await bot.prompt_claim(msg, state)
    state.clear.assert_not_called()
    assert str(bot.MAX_CLAIM_LENGTH) in msg.answer.call_args[0][0]


async def test_prompt_claim_slash_text_cancels_prompt():
    # An unknown command mid-prompt: state was already cleared by the
    # ClearPromptOnCommandMiddleware; the handler must not treat it as a claim.
    msg = _mock_msg()
    msg.text = "/unknowncmd"
    state = _mock_state(None)
    mock_fn = AsyncMock()
    with patch("analyzer.fact_check", new=mock_fn):
        await bot.prompt_claim(msg, state)
    mock_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Prompt flow — /thread via button
# ---------------------------------------------------------------------------

async def test_thread_no_url_starts_prompt():
    from unittest.mock import MagicMock
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = None
    state = _mock_state()
    await bot.cmd_thread(msg, cmd, state)
    state.set_state.assert_called_once_with(bot.PromptFlow.awaiting_thread_url)
    assert "/cancel" in msg.answer.call_args[0][0]


async def test_thread_with_url_does_not_enter_prompt():
    from unittest.mock import MagicMock
    import voz
    msg = _mock_msg()
    cmd = MagicMock()
    cmd.args = "https://voz.vn/t/abc.123456/"
    state = _mock_state()
    thread = voz.Thread(title="T", url=cmd.args, posts=[])
    with patch("voz.fetch_thread", new=AsyncMock(return_value=thread)), \
         patch("analyzer.thread_summary", new=AsyncMock(return_value="tóm tắt")):
        await bot.cmd_thread(msg, cmd, state)
    state.set_state.assert_not_called()


async def test_prompt_thread_url_invalid_reprompts_and_keeps_state():
    msg = _mock_msg()
    msg.text = "https://evil.com/t/x.1/"
    state = _mock_state(bot.PromptFlow.awaiting_thread_url.state)
    await bot.prompt_thread_url(msg, state)
    state.clear.assert_not_called()
    assert "voz" in msg.answer.call_args[0][0]


async def test_prompt_thread_url_valid_runs_summary_and_clears_state():
    import voz
    msg = _mock_msg()
    msg.text = "https://voz.vn/t/abc.123456/"
    state = _mock_state(bot.PromptFlow.awaiting_thread_url.state)
    thread = voz.Thread(title="T", url=msg.text, posts=[])
    mock_fn = AsyncMock(return_value="tóm tắt")
    with patch("voz.fetch_thread", new=AsyncMock(return_value=thread)), \
         patch("analyzer.thread_summary", new=mock_fn):
        await bot.prompt_thread_url(msg, state)
    state.clear.assert_called_once()
    mock_fn.assert_called_once()


# ---------------------------------------------------------------------------
# /cancel
# ---------------------------------------------------------------------------

async def test_cancel_clears_active_prompt():
    msg = _mock_msg()
    state = _mock_state(bot.PromptFlow.awaiting_claim.state)
    await bot.cmd_cancel(msg, state)
    state.clear.assert_called_once()
    assert "cancel" in msg.answer.call_args[0][0].lower()


async def test_cancel_without_prompt_says_nothing_to_cancel():
    msg = _mock_msg()
    state = _mock_state(None)
    await bot.cmd_cancel(msg, state)
    state.clear.assert_not_called()
    assert "nothing" in msg.answer.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# config.OWNER_ID
# ---------------------------------------------------------------------------

def test_config_owner_id_is_integer():
    import config
    assert isinstance(config.OWNER_ID, int)
    assert config.OWNER_ID == int(os.environ["OWNER_ID"])
