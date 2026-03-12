import asyncio

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
from bot import build_dispatcher
from buffer import MessageBuffer
from crawler import TelegramCrawler


async def main() -> None:
    buffer = MessageBuffer(maxsize=config.BUFFER_SIZE)
    crawler = TelegramCrawler(buffer)
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = build_dispatcher(buffer, bot)

    print("Starting Telegram Intel Bot...")
    await asyncio.gather(
        crawler.start(config.CHANNELS),
        dp.start_polling(bot),
    )


if __name__ == "__main__":
    asyncio.run(main())
