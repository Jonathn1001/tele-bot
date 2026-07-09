import logging
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message as TgMessage
from aiogram.types import TelegramObject

import analyzer
import config
import hn
import voz
from buffer import MessageBuffer

logger = logging.getLogger(__name__)


class OwnerOnlyMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user is None or event.from_user.id != config.OWNER_ID:
            return
        return await handler(event, data)


# Commands that trigger a paid Gemini API call — these get a cooldown.
ANALYSIS_COMMANDS = ("/summary", "/threat", "/factcheck", "/hn", "/paper", "/thread")


class RateLimitMiddleware(BaseMiddleware):
    """Cooldown between analysis commands so a runaway client can't drain the Gemini quota."""

    def __init__(self, cooldown_seconds: int) -> None:
        self._cooldown = cooldown_seconds
        self._last_call: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        text = getattr(event, "text", None) or ""
        if self._cooldown <= 0 or not text.startswith(ANALYSIS_COMMANDS):
            return await handler(event, data)
        now = monotonic()
        last = self._last_call.get(event.from_user.id)
        if last is not None and now - last < self._cooldown:
            wait = int(self._cooldown - (now - last)) + 1
            await event.answer(f"Rate limit: please wait {wait}s before the next analysis.")
            return
        self._last_call[event.from_user.id] = now
        return await handler(event, data)


router = Router()
router.message.middleware(OwnerOnlyMiddleware())
router.message.middleware(RateLimitMiddleware(config.RATE_LIMIT_SECONDS))

EMPTY_BUFFER_REPLY = (
    "No messages collected yet — the crawler may still be backfilling. "
    "Try again in a minute."
)
_buffer: MessageBuffer | None = None
MAX_CLAIM_LENGTH = 500


def build_dispatcher(buffer: MessageBuffer, bot: Bot) -> Dispatcher:
    global _buffer
    _buffer = buffer
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _split(text: str, limit: int = 4096) -> list[str]:
    """Chunk to Telegram's message limit, preferring paragraph then line breaks
    so replies don't get cut mid-sentence. Falls back to a hard slice only for a
    single line longer than the limit."""
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        # Break at the last paragraph gap, else the last line break, else hard-cut.
        cut = window.rfind("\n\n")
        if cut == -1:
            cut = window.rfind("\n")
        if cut == -1:
            cut = limit
        chunks.append(remaining[:cut].rstrip("\n"))
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


async def _reply_analysis(message: TgMessage, result: str) -> None:
    for chunk in _split(result):
        await message.answer(chunk, parse_mode=None)


async def send_to_owner(bot: Bot, text: str) -> None:
    """Push a scheduled digest to the owner, chunked to Telegram's limit."""
    for chunk in _split(text):
        await bot.send_message(config.OWNER_ID, chunk, parse_mode=None)


@router.message(Command("start"))
async def cmd_start(message: TgMessage) -> None:
    await message.answer(
        "*Telegram Intel Bot*\n\n"
        "I monitor political and military news channels and provide AI-powered analysis on demand.\n\n"
        "*Commands*\n"
        "/summary — Top 5 significant events from recent messages\n"
        "/threat — Conflict risk assessment (1–5 scale)\n"
        "/factcheck <claim> — Verify a claim against channels + web sources\n"
        "      e.g. `/factcheck Russia closed the border today`\n"
        "/hn — Security stories on Hacker News right now\n"
        "/paper — Điểm báo: press review from voz.vn f/Điểm báo\n"
        "/thread <voz url> — Summarize the recent comments on a voz thread\n"
        "      e.g. `/thread https://voz.vn/t/abc.123456/`\n"
        "/channels — Monitored channels and message counts\n\n"
        "Scheduled pushes: HN security digest 08:30 & 20:00, điểm báo 07:00 (VN time).\n"
        "Analysis replies are bilingual: English + Tiếng Việt.",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("channels"))
async def cmd_channels(message: TgMessage) -> None:
    if _buffer is None or _buffer.is_empty():
        await message.answer(EMPTY_BUFFER_REPLY)
        return
    sizes = _buffer.channel_sizes()
    lines = [f"• `{ch}` — {n} messages" for ch, n in sizes.items()]
    await message.answer(
        f"📡 *Monitored channels* — {_buffer.total_size()} messages buffered:\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("summary"))
async def cmd_summary(message: TgMessage) -> None:
    if _buffer is None or _buffer.is_empty():
        await message.answer(EMPTY_BUFFER_REPLY)
        return
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    await message.answer(f"📋 Summarizing the last {len(msgs)} messages… (~10s)")
    result = await analyzer.summarize(msgs)
    await _reply_analysis(message, result)



@router.message(Command("threat"))
async def cmd_threat(message: TgMessage) -> None:
    if _buffer is None or _buffer.is_empty():
        await message.answer(EMPTY_BUFFER_REPLY)
        return
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    await message.answer(f"⚠️ Assessing threat level from the last {len(msgs)} messages… (~10s)")
    result = await analyzer.assess_threat(msgs)
    await _reply_analysis(message, result)


@router.message(Command("hn"))
async def cmd_hn(message: TgMessage) -> None:
    await message.answer("🔐 Fetching security stories from Hacker News… (~20s)")
    try:
        stories = await hn.fetch_security_stories()
    except Exception:
        logger.exception("HN fetch failed")
        await message.answer(analyzer.ANALYSIS_FAILED_REPLY)
        return
    result = await analyzer.hn_digest(stories)
    await _reply_analysis(message, result)


@router.message(Command("paper"))
async def cmd_paper(message: TgMessage) -> None:
    await message.answer("📰 Đang soạn điểm báo từ voz (f/Điểm báo)… (~30s)")
    headlines = await voz.fetch_headlines()
    result = await analyzer.press_digest(headlines)
    await _reply_analysis(message, result)


@router.message(Command("thread"))
async def cmd_thread(message: TgMessage, command: CommandObject) -> None:
    url = (command.args or "").strip()
    if not url:
        await message.answer(
            "Usage: /thread <voz thread url>\n"
            "Example: /thread https://voz.vn/t/abc.123456/"
        )
        return
    if voz.normalize_thread_url(url) is None:
        await message.answer("Đó không phải link thread voz hợp lệ (cần dạng voz.vn/t/…/).")
        return
    await message.answer("🧵 Đang đọc bình luận mới nhất trên thread voz… (~30s)")
    thread = await voz.fetch_thread(url)
    if thread is None:
        await message.answer(analyzer.ANALYSIS_FAILED_REPLY)
        return
    result = await analyzer.thread_summary(thread)
    await _reply_analysis(message, result)


@router.message(Command("factcheck"))
async def cmd_factcheck(message: TgMessage, command: CommandObject) -> None:
    claim = (command.args or "").strip()
    if not claim:
        await message.answer(
            "Usage: /factcheck <your claim>\n"
            "Example: /factcheck Russia closed the border today"
        )
        return
    if len(claim) > MAX_CLAIM_LENGTH:
        await message.answer(f"Claim too long. Please keep it under {MAX_CLAIM_LENGTH} characters.")
        return
    if _buffer is None or _buffer.is_empty():
        await message.answer(EMPTY_BUFFER_REPLY)
        return
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    await message.answer(f"🔎 Fact-checking against {len(msgs)} channel messages + web sources… (~20s)")
    result = await analyzer.fact_check(claim, msgs)
    await _reply_analysis(message, result)
