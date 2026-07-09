import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# (fire time in VN_TZ, job name for logs, zero-arg coroutine function)
Job = tuple[time, str, Callable[[], Awaitable[None]]]


def parse_times(spec: str) -> list[time]:
    """'08:30,20:00' -> [time(8, 30), time(20, 0)]. Raises ValueError on junk."""
    times = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        hour, minute = part.split(":")
        times.append(time(int(hour), int(minute)))
    return times


def next_run(now: datetime, fire: time) -> datetime:
    candidate = now.replace(hour=fire.hour, minute=fire.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


async def run_scheduler(jobs: list[Job]) -> None:
    """Sleep until the nearest job's fire time, run it, repeat. Job crashes are logged, never fatal."""
    if not jobs:
        return
    while True:
        now = datetime.now(VN_TZ)
        when, name, fn = min(
            ((next_run(now, t), name, fn) for t, name, fn in jobs),
            key=lambda x: x[0],
        )
        delay = (when - now).total_seconds()
        logger.info("Scheduler: next job %r at %s (in %.0f min)", name, when.isoformat(), delay / 60)
        await asyncio.sleep(delay)
        try:
            await fn()
            logger.info("Scheduler: job %r done", name)
        except Exception:
            logger.exception("Scheduler: job %r failed", name)
