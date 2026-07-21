import asyncio
import logging
from datetime import datetime

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

import analyzer
import config
import db
import health
import hn
import notion
from alerts import AlertMatcher
from bot import build_dispatcher, build_press_report, send_to_owner, setup_bot_commands
from buffer import Message, MessageBuffer
from crawler import TelegramCrawler
from scheduler import VN_TZ, Job, parse_times, run_scheduler

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30  # seconds between liveness pings; watchdog trips at 180s


async def run_weekly_review(bot: Bot, now: datetime | None = None) -> None:
    """Sunday-only: push this week's review, then clone next week's page. The two
    halves are isolated — a review (fetch/analyze) failure still lets the clone run
    (it re-reads the source page), and a clone failure never blocks the review.
    Module-level (not a closure) so the isolation contract is unit-testable."""
    now = now or datetime.now(VN_TZ)
    if now.weekday() != 6:  # 6 = Sunday
        return
    page = await notion.find_current_week_page(now.date())  # fails soft → None
    if page is None:
        await send_to_owner(bot, "📝 Weekly review: couldn't find this week's Notion page.")
    else:
        try:
            week = await notion.fetch_week(page.id)
            text = await analyzer.weekly_review(week)
            await send_to_owner(bot, f"📝 Weekly Review — {week.label}\n\n{text}")
        except Exception:
            logger.exception("weekly: review failed")
            await send_to_owner(bot, "📝 Weekly review failed — couldn't read this week's page.")
    # Clone runs regardless of the review outcome; it only needs the located page.
    if config.AUTOCREATE_ENABLED and page is not None:
        try:
            new_id = await notion.create_next_week(now.date(), source_page_id=page.id)
            if new_id:
                await send_to_owner(bot, "🆕 Next week's to-do page is ready.")
        except Exception:
            logger.exception("weekly: create_next_week failed")
            await send_to_owner(bot, "⚠️ Couldn't create next week's page.")


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
        text = await build_press_report()
        await send_to_owner(bot, f"📰 Điểm báo sáng (voz)\n\n{text}")

    async def weekly_review_job() -> None:
        # Fires daily at WEEKLY_REVIEW_TIME; run_weekly_review self-guards to Sunday.
        await run_weekly_review(bot)

    jobs: list[Job] = [
        *((t, "hn_digest", hn_job) for t in parse_times(config.HN_DIGEST_TIMES)),
        *((t, "press_digest", press_job) for t in parse_times(config.PRESS_DIGEST_TIMES)),
        *(
            (t, "weekly_review", weekly_review_job)
            for t in (parse_times(config.WEEKLY_REVIEW_TIME) if config.WEEKLY_ENABLED else [])
        ),
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
