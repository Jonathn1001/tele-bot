import asyncio
import logging
from collections.abc import Awaitable, Callable

from telethon import TelegramClient, events
from telethon.sessions import StringSession

import config
import db
from buffer import Message, MessageBuffer

logger = logging.getLogger(__name__)

# Called with (message, matched_keywords) for each live message that matches
# the alert watchlist. Never invoked during backfill.
AlertCallback = Callable[[Message, list[str]], Awaitable[None]]


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

    async def start(
        self,
        channels: list[str],
        alert_cb: AlertCallback | None = None,
        alert_matcher=None,
    ) -> None:
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

            # Keyword alerts fire only on live messages, never on backfill,
            # so a restart doesn't replay old alerts.
            if alert_cb is not None and alert_matcher is not None:
                hits = alert_matcher.match(msg.text)
                if hits:
                    asyncio.create_task(self._safe_alert(alert_cb, msg, hits))

        logger.info("Crawler: monitoring %s", channels)
        await self._client.run_until_disconnected()

    @staticmethod
    async def _safe_alert(alert_cb: AlertCallback, msg: Message, hits: list[str]) -> None:
        try:
            await alert_cb(msg, hits)
        except Exception:
            logger.exception("Crawler: alert callback failed for %s", msg.channel)

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
