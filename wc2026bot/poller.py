import asyncio
import logging
from datetime import datetime, timedelta

from wc2026bot.state import apply_result

log = logging.getLogger(__name__)


def poll_interval(now: datetime, next_kickoff: datetime | None,
                  any_live: bool) -> int:
    if any_live:
        return 60
    if next_kickoff is not None and next_kickoff - now <= timedelta(minutes=30):
        return 300
    return 21600


async def poll_once(conn, clients) -> list[str]:
    finished: list[str] = []
    for c in clients:
        try:
            results = await c.fetch()
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", type(c).__name__, e)
            continue
        for r in results:
            if apply_result(conn, r):
                finished.append(r.match_id)
    return finished


async def run_poller(conn, clients, on_finished, stop_event) -> None:
    while not stop_event.is_set():
        try:
            finished = await poll_once(conn, clients)
            if finished:
                await on_finished(finished)
            any_live = conn.execute(
                "SELECT 1 FROM matches WHERE status='LIVE' LIMIT 1"
            ).fetchone() is not None
            nk = conn.execute(
                "SELECT MIN(kickoff_time) k FROM matches WHERE status='SCHEDULED'"
            ).fetchone()["k"]
            next_kickoff = (datetime.fromisoformat(nk.replace("Z", "+00:00"))
                            if nk else None)
            delay = poll_interval(datetime.now().astimezone(),
                                  next_kickoff, any_live)
        except Exception as e:  # noqa: BLE001
            log.exception("poll cycle error: %s", e)
            delay = 300
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
