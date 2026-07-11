import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import analyzer
import config
import db
import health
import hn
import voz
from alerts import AlertMatcher
from bot import build_dispatcher, send_to_owner, setup_bot_commands
from buffer import Message, MessageBuffer
from crawler import TelegramCrawler
from scheduler import Job, parse_times, run_scheduler

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds between liveness pings; watchdog trips at 180s


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

    async def heartbeat() -> None:
        while True:
            health.touch()
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    matcher = AlertMatcher(config.ALERT_KEYWORDS)

    async def on_alert(msg: Message, keywords: list[str]) -> None:
        kw = ", ".join(keywords)
        body = msg.text if len(msg.text) <= 1500 else msg.text[:1500] + "…"
        await send_to_owner(
            bot,
            f"🚨 Alert [{kw}] in {msg.channel}\n"
            f"{msg.date:%Y-%m-%d %H:%M}\n\n{body}",
        )

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

    health.touch()  # seed the heartbeat before the watchdog's grace period starts
    health.start_watchdog()
    if matcher.enabled:
        logger.info("Alerts: watching %d keywords", len(config.ALERT_KEYWORDS))

    try:
        await setup_bot_commands(bot)
    except Exception:
        logger.exception("set_my_commands failed; '/' menu may be stale")

    logger.info("Starting Telegram Intel Bot...")
    await asyncio.gather(
        crawler.start(config.CHANNELS, alert_cb=on_alert, alert_matcher=matcher),
        dp.start_polling(bot),
        pruner(),
        heartbeat(),
        run_scheduler(jobs),
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(main())
