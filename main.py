import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import analyzer
import config
import db
import hn
import voz
from bot import build_dispatcher, send_to_owner
from buffer import MessageBuffer
from crawler import TelegramCrawler
from scheduler import Job, parse_times, run_scheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    pool = await db.init_pool(config.DATABASE_URL, config.DATABASE_CA_CERT, config.DATABASE_SSL)
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

    async def hn_job() -> None:
        stories = await hn.fetch_security_stories()
        text = await analyzer.hn_digest(stories)
        await send_to_owner(bot, f"🔐 HN Security Digest\n\n{text}")

    async def press_job() -> None:
        headlines = await voz.fetch_headlines()
        text = await analyzer.press_digest(headlines)
        await send_to_owner(bot, f"📰 Điểm báo sáng (voz)\n\n{text}")

    jobs: list[Job] = [
        *((t, "hn_digest", hn_job) for t in parse_times(config.HN_DIGEST_TIMES)),
        *((t, "press_digest", press_job) for t in parse_times(config.PRESS_DIGEST_TIMES)),
    ]

    logger.info("Starting Telegram Intel Bot...")
    await asyncio.gather(
        crawler.start(config.CHANNELS),
        dp.start_polling(bot),
        pruner(),
        run_scheduler(jobs),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
