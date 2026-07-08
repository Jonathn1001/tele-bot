from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject
from aiogram.types import Message as TgMessage
from aiogram.types import TelegramObject

import analyzer
import config
from buffer import MessageBuffer


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


router = Router()
router.message.middleware(OwnerOnlyMiddleware())
_buffer: MessageBuffer | None = None
MAX_CLAIM_LENGTH = 500


def build_dispatcher(buffer: MessageBuffer, bot: Bot) -> Dispatcher:
    global _buffer
    _buffer = buffer
    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _split(text: str, limit: int = 4096) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)]


async def _reply_analysis(message: TgMessage, result: str) -> None:
    for chunk in _split(result):
        await message.answer(chunk, parse_mode=None)


@router.message(Command("start"))
async def cmd_start(message: TgMessage) -> None:
    await message.answer(
        "*Telegram Intel Bot*\n\n"
        "I monitor political and military news channels and provide AI-powered analysis.\n\n"
        "Commands:\n"
        "/summary — Key events from recent messages\n"
        "/factcheck <claim> — Verify a claim against channel messages + web sources\n"
        "/threat — Conflict risk assessment\n"
        "/channels — Monitored channels status",
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("channels"))
async def cmd_channels(message: TgMessage) -> None:
    if _buffer is None or _buffer.is_empty():
        await message.answer("No messages collected yet.")
        return
    sizes = _buffer.channel_sizes()
    lines = [f"• `{ch}`: {n} messages" for ch, n in sizes.items()]
    await message.answer(
        f"*Monitored channels* ({_buffer.total_size()} total):\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
    )


@router.message(Command("summary"))
async def cmd_summary(message: TgMessage) -> None:
    if _buffer is None or _buffer.is_empty():
        await message.answer("No messages collected yet. Please wait a moment.")
        return
    await message.answer("Analyzing...")
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    result = await analyzer.summarize(msgs)
    await _reply_analysis(message, result)



@router.message(Command("threat"))
async def cmd_threat(message: TgMessage) -> None:
    if _buffer is None or _buffer.is_empty():
        await message.answer("No messages collected yet. Please wait a moment.")
        return
    await message.answer("Analyzing...")
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    result = await analyzer.assess_threat(msgs)
    await _reply_analysis(message, result)


@router.message(Command("factcheck"))
async def cmd_factcheck(message: TgMessage, command: CommandObject) -> None:
    claim = (command.args or "").strip()
    if not claim:
        await message.answer("Usage: /factcheck <your claim>")
        return
    if len(claim) > MAX_CLAIM_LENGTH:
        await message.answer(f"Claim too long. Please keep it under {MAX_CLAIM_LENGTH} characters.")
        return
    if _buffer is None or _buffer.is_empty():
        await message.answer("No messages collected yet. Please wait a moment.")
        return
    await message.answer("Analyzing...")
    msgs = _buffer.get_all(limit=config.MAX_CONTEXT_MESSAGES)
    result = await analyzer.fact_check(claim, msgs)
    await _reply_analysis(message, result)
