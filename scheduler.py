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


def next_wave(
    now: datetime, jobs: list[Job]
) -> tuple[datetime, list[tuple[str, Callable[[], Awaitable[None]]]]]:
    """Earliest upcoming fire time and *every* job that fires at it.

    Jobs sharing a fire time are batched into one wave so none is starved —
    the old min()-picks-one logic silently dropped every tie-loser each day.
    """
    scheduled = [(next_run(now, t), name, fn) for t, name, fn in jobs]
    when = min(w for w, _, _ in scheduled)
    due = [(name, fn) for w, name, fn in scheduled if w == when]
    return when, due


async def run_scheduler(jobs: list[Job]) -> None:
    """Sleep until the nearest fire time, run every job due then, repeat. Job crashes are logged, never fatal."""
    if not jobs:
        return
    while True:
        now = datetime.now(VN_TZ)
        when, due = next_wave(now, jobs)
        delay = (when - now).total_seconds()
        logger.info(
            "Scheduler: %d job(s) at %s (in %.0f min)", len(due), when.isoformat(), delay / 60
        )
        await asyncio.sleep(delay)
        for name, fn in due:
            try:
                await fn()
                logger.info("Scheduler: job %r done", name)
            except Exception:
                logger.exception("Scheduler: job %r failed", name)
