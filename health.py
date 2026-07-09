import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

HEARTBEAT_PATH = os.environ.get("HEARTBEAT_PATH", "/tmp/heartbeat")


def touch(path: str = HEARTBEAT_PATH) -> None:
    """Record liveness by bumping the heartbeat file's mtime."""
    with open(path, "w") as f:
        f.write(str(time.time()))


def is_fresh(path: str = HEARTBEAT_PATH, max_age: float = 180.0) -> bool:
    """True if the heartbeat was written within max_age seconds."""
    try:
        return (time.time() - os.path.getmtime(path)) <= max_age
    except OSError:
        return False


def start_watchdog(
    path: str = HEARTBEAT_PATH,
    max_age: float = 180.0,
    check_interval: float = 30.0,
) -> None:
    """Dead-man's-switch: a daemon OS thread (survives an asyncio event-loop
    stall) that force-exits the process if the heartbeat goes stale, so Docker's
    `restart: unless-stopped` brings up a fresh container. The heartbeat is
    refreshed by an asyncio task, so if the loop wedges the file ages out."""

    def _loop() -> None:
        # Grace period so startup (imports, backfill) doesn't trip the switch.
        time.sleep(max_age)
        while True:
            if not is_fresh(path, max_age):
                logger.error(
                    "Watchdog: heartbeat stale (> %.0fs) — exiting for restart", max_age
                )
                os._exit(1)
            time.sleep(check_interval)

    threading.Thread(target=_loop, name="watchdog", daemon=True).start()
