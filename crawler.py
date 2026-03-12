from telethon import TelegramClient, events
from telethon.sessions import StringSession

import config
from buffer import Message, MessageBuffer


class TelegramCrawler:
    def __init__(self, buffer: MessageBuffer) -> None:
        self._buffer = buffer
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

        print(f"Crawler: monitoring {channels}")
        await self._client.run_until_disconnected()

    async def _backfill(self, channel: str) -> None:
        print(f"Crawler: backfilling {channel}...")
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
        print(f"Crawler: backfill complete for {channel} ({self._buffer.total_size()} messages)")
