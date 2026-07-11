import os

os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from unittest.mock import AsyncMock, MagicMock

import config
import bot


def _make_message(user_id: int | None) -> MagicMock:
    """Build a mock aiogram Message with the given from_user.id (or None)."""
    msg = MagicMock()
    if user_id is None:
        msg.from_user = None
    else:
        msg.from_user = MagicMock()
        msg.from_user.id = user_id
    return msg


async def test_owner_message_passes_through():
    """Owner's messages reach the handler."""
    middleware = bot.OwnerOnlyMiddleware()
    handler = AsyncMock()
    msg = _make_message(config.OWNER_ID)
    await middleware(handler, msg, {})
    handler.assert_called_once_with(msg, {})


async def test_stranger_message_is_dropped():
    """Messages from unknown users are silently dropped."""
    middleware = bot.OwnerOnlyMiddleware()
    handler = AsyncMock()
    msg = _make_message(config.OWNER_ID + 1)  # any ID that isn't the owner's
    await middleware(handler, msg, {})
    handler.assert_not_called()


async def test_anonymous_message_is_dropped():
    """Messages with from_user=None (e.g. anonymous channel posts) are silently dropped."""
    middleware = bot.OwnerOnlyMiddleware()
    handler = AsyncMock()
    msg = _make_message(None)
    await middleware(handler, msg, {})
    handler.assert_not_called()


def test_middleware_registered_on_router():
    """OwnerOnlyMiddleware must be registered on the module-level router exactly once."""
    registered = [
        m for m in bot.router.message.middleware
        if isinstance(m, bot.OwnerOnlyMiddleware)
    ]
    assert len(registered) == 1


# ---------------------------------------------------------------------------
# RateLimitMiddleware
# ---------------------------------------------------------------------------

def _make_command_message(user_id: int, text: str) -> MagicMock:
    msg = _make_message(user_id)
    msg.text = text
    msg.answer = AsyncMock()
    return msg


async def test_rate_limit_allows_first_analysis_call():
    middleware = bot.RateLimitMiddleware(cooldown_seconds=15)
    handler = AsyncMock()
    msg = _make_command_message(config.OWNER_ID, "/summary")
    await middleware(handler, msg, {})
    handler.assert_called_once()


async def test_rate_limit_blocks_second_call_within_cooldown():
    middleware = bot.RateLimitMiddleware(cooldown_seconds=15)
    handler = AsyncMock()
    first = _make_command_message(config.OWNER_ID, "/summary")
    second = _make_command_message(config.OWNER_ID, "/threat")
    await middleware(handler, first, {})
    await middleware(handler, second, {})
    handler.assert_called_once()  # second call dropped
    second.answer.assert_called_once()
    assert "wait" in second.answer.call_args[0][0].lower()


async def test_rate_limit_ignores_non_analysis_commands():
    middleware = bot.RateLimitMiddleware(cooldown_seconds=15)
    handler = AsyncMock()
    for text in ("/start", "/channels", "/summary"):
        await middleware(handler, _make_command_message(config.OWNER_ID, text), {})
    assert handler.call_count == 3  # /start and /channels never throttled


async def test_rate_limit_disabled_when_zero():
    middleware = bot.RateLimitMiddleware(cooldown_seconds=0)
    handler = AsyncMock()
    for _ in range(3):
        await middleware(handler, _make_command_message(config.OWNER_ID, "/summary"), {})
    assert handler.call_count == 3


async def test_rate_limit_allows_after_cooldown_expiry():
    middleware = bot.RateLimitMiddleware(cooldown_seconds=15)
    handler = AsyncMock()
    msg1 = _make_command_message(config.OWNER_ID, "/summary")
    msg2 = _make_command_message(config.OWNER_ID, "/summary")
    await middleware(handler, msg1, {})
    # simulate cooldown passed
    middleware._last_call[config.OWNER_ID] -= 16
    await middleware(handler, msg2, {})
    assert handler.call_count == 2


# ---------------------------------------------------------------------------
# ClearPromptOnCommandMiddleware — commands always win over a pending prompt
# ---------------------------------------------------------------------------

def _make_text_message(text: str) -> MagicMock:
    msg = _make_message(config.OWNER_ID)
    msg.text = text
    return msg


def _make_state(current: str | None) -> AsyncMock:
    st = AsyncMock()
    st.get_state = AsyncMock(return_value=current)
    return st


async def test_command_clears_active_prompt_state():
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    msg = _make_text_message("/summary")
    await mw(handler, msg, {"state": state})
    state.clear.assert_called_once()
    handler.assert_called_once()


async def test_cancel_command_keeps_state_for_its_handler():
    """cmd_cancel reads the state itself to reply accurately — don't pre-clear."""
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    msg = _make_text_message("/cancel")
    await mw(handler, msg, {"state": state})
    state.clear.assert_not_called()
    handler.assert_called_once()


async def test_plain_text_does_not_touch_state():
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(bot.PromptFlow.awaiting_claim.state)
    msg = _make_text_message("just a claim")
    await mw(handler, msg, {"state": state})
    state.clear.assert_not_called()
    handler.assert_called_once()


async def test_command_without_active_state_is_untouched():
    mw = bot.ClearPromptOnCommandMiddleware()
    handler = AsyncMock()
    state = _make_state(None)
    msg = _make_text_message("/summary")
    await mw(handler, msg, {"state": state})
    state.clear.assert_not_called()
    handler.assert_called_once()


def test_clear_prompt_middleware_registered_between_owner_and_ratelimit():
    kinds = [type(m).__name__ for m in bot.router.message.middleware]
    owner = kinds.index("OwnerOnlyMiddleware")
    clear = kinds.index("ClearPromptOnCommandMiddleware")
    rate = kinds.index("RateLimitMiddleware")
    assert owner < clear < rate
