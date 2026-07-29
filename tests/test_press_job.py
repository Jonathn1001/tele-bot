import os

# Must be set before any project module is imported (config reads env at import).
os.environ.setdefault("TELEGRAM_API_ID", "12345")
os.environ.setdefault("TELEGRAM_API_HASH", "dummy_hash")
os.environ.setdefault("BOT_TOKEN", "0:AADummy")
os.environ.setdefault("GEMINI_API_KEY", "dummy_key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")

from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest

import config
import main

GROUP_ID = -5424560152


def _bad_request(message: str) -> TelegramBadRequest:
    return TelegramBadRequest(method=AsyncMock(), message=message)


async def test_press_digest_goes_to_configured_chat(monkeypatch):
    send = AsyncMock()
    monkeypatch.setattr(config, "PRESS_CHAT_ID", GROUP_ID)
    monkeypatch.setattr(main, "send_to_chat", send)
    monkeypatch.setattr(main, "build_press_report", AsyncMock(return_value="điểm báo"))

    await main.run_press_digest(AsyncMock())

    send.assert_awaited_once()
    assert send.await_args.args[1] == GROUP_ID
    assert "điểm báo" in send.await_args.args[2]


async def test_press_digest_falls_back_to_owner_when_chat_send_fails(monkeypatch):
    send = AsyncMock(side_effect=_bad_request("chat not found"))
    owner = AsyncMock()
    monkeypatch.setattr(config, "PRESS_CHAT_ID", GROUP_ID)
    monkeypatch.setattr(main, "send_to_chat", send)
    monkeypatch.setattr(main, "send_to_owner", owner)
    monkeypatch.setattr(main, "build_press_report", AsyncMock(return_value="điểm báo"))

    await main.run_press_digest(AsyncMock())

    owner.assert_awaited_once()
    # The report itself is not re-sent to the owner — only a delivery warning.
    assert "điểm báo" not in owner.await_args.args[1]


async def test_press_digest_does_not_double_send_when_target_is_owner(monkeypatch):
    send = AsyncMock(side_effect=_bad_request("chat not found"))
    owner = AsyncMock()
    monkeypatch.setattr(config, "PRESS_CHAT_ID", config.OWNER_ID)
    monkeypatch.setattr(main, "send_to_chat", send)
    monkeypatch.setattr(main, "send_to_owner", owner)
    monkeypatch.setattr(main, "build_press_report", AsyncMock(return_value="điểm báo"))

    await main.run_press_digest(AsyncMock())

    owner.assert_not_awaited()


def test_press_chat_id_defaults_to_owner(monkeypatch):
    # Empty (not unset) — load_dotenv never overrides an already-set var, so a real
    # .env on the dev box can't leak a group id into this assertion.
    monkeypatch.setenv("PRESS_CHAT_ID", "")
    import importlib

    reloaded = importlib.reload(config)
    try:
        assert reloaded.PRESS_CHAT_ID == reloaded.OWNER_ID
    finally:
        importlib.reload(config)  # restore module state for the rest of the session
