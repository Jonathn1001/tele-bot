"""Tests for startup-level correctness (no real API keys required)."""
import os
import sys

import pytest

# Provide dummy env vars so config.py doesn't raise KeyError at import time
os.environ.setdefault("TELEGRAM_API_ID", "12345678")
os.environ.setdefault("TELEGRAM_API_HASH", "0" * 32)
os.environ.setdefault("BOT_TOKEN", "123456789:AABBCCDDEEFFaabbccddeeff12345678901")
os.environ.setdefault("GEMINI_API_KEY", "dummy-key")
os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")
os.environ.setdefault("OWNER_ID", "5730878656")


def test_bot_created_with_default_properties():
    """Bot must be initialised with DefaultBotProperties, not bare parse_mode kwarg."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties
    from aiogram.enums import ParseMode

    # This is the CORRECT way in aiogram >= 3.7
    bot = Bot(
        token=os.environ["BOT_TOKEN"],
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    assert bot.default.parse_mode == ParseMode.MARKDOWN


def test_bot_old_style_init_raises():
    """Confirm that the old-style parse_mode kwarg raises TypeError (regression guard)."""
    from aiogram import Bot
    from aiogram.enums import ParseMode

    with pytest.raises(TypeError):
        Bot(token=os.environ["BOT_TOKEN"], parse_mode=ParseMode.MARKDOWN)
