import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import config
import db
from bot import build_dispatcher
from buffer import MessageBuffer
from crawler import TelegramCrawler

logger = logging.getLogger(__name__)


async def main() -> None:
    pool = await db.init_pool(config.DATABASE_URL, config.DATABASE_CA_CERT)
    buffer = MessageBuffer(maxsize=config.BUFFER_SIZE)
    crawler = TelegramCrawler(buffer, pool)
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = build_dispatcher(buffer, bot)

    async def pruner() -> None:
        while True:
            await asyncio.sleep(config.PRUNE_INTERVAL_HOURS * 3600)
            try:
                await db.prune_old_messages(pool, config.RETENTION_DAYS)
            except Exception:
                logger.exception("Pruner: error during prune")

    logger.info("Starting Telegram Intel Bot...")
    await asyncio.gather(
        crawler.start(config.CHANNELS),
        dp.start_polling(bot),
        pruner(),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
