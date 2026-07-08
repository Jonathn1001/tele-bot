import asyncio
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession

import config
import db
from buffer import Message, MessageBuffer

logger = logging.getLogger(__name__)


class TelegramCrawler:
    def __init__(self, buffer: MessageBuffer, pool: "asyncpg.Pool") -> None:
        self._buffer = buffer
        self._pool = pool
        session = StringSession(config.SESSION_STRING) if config.SESSION_STRING else "session"
        self._client = TelegramClient(
            session,
            config.TELEGRAM_API_ID,
            config.TELEGRAM_API_HASH,
            connection_retries=None,
        )

    async def start(self, channels: list[str]) -> None:
        await self._client.start()

        for channel in channels:
            await self._backfill(channel)

        @self._client.on(events.NewMessage(chats=channels))
        async def handler(event: events.NewMessage.Event) -> None:
            if not event.message.text:
                return
            chat = await event.get_chat()
            channel_name = getattr(chat, "username", None) or str(chat.id)
            channel_name = f"@{channel_name}" if not channel_name.startswith("@") else channel_name
            sender = getattr(event.message.sender, "username", None)
            msg = Message(
                channel=channel_name,
                text=event.message.text,
                date=event.message.date.replace(tzinfo=None),
                sender=sender,
            )
            self._buffer.add(channel_name, msg)
            def _on_done(t: asyncio.Task, ch: str = channel_name) -> None:
                if not t.cancelled() and t.exception():
                    logger.error("Crawler: DB insert failed for %s: %s", ch, t.exception())
            asyncio.create_task(db.insert_message(self._pool, msg)).add_done_callback(_on_done)

        logger.info("Crawler: monitoring %s", channels)
        await self._client.run_until_disconnected()

    async def _backfill(self, channel: str) -> None:
        logger.info("Crawler: backfilling %s...", channel)
        async for message in self._client.iter_messages(channel, limit=config.BUFFER_SIZE):
            if not message.text:
                continue
            channel_name = f"@{channel.lstrip('@')}"
            sender = getattr(message.sender, "username", None)
            msg = Message(
                channel=channel_name,
                text=message.text,
                date=message.date.replace(tzinfo=None),
                sender=sender,
            )
            self._buffer.add(channel_name, msg)
            try:
                await db.insert_message(self._pool, msg)
            except Exception:
                logger.exception("Crawler: DB insert failed during backfill for %s", channel_name)
        logger.info("Crawler: backfill complete for %s (%d messages)", channel, self._buffer.total_size())
