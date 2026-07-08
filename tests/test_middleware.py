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
