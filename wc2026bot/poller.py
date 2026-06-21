import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from wc2026bot.state import apply_result_ex

log = logging.getLogger(__name__)


@dataclass
class PollOutcome:
    finished: list[str] = field(default_factory=list)
    goals: list[str] = field(default_factory=list)


def poll_interval(now: datetime, next_kickoff: datetime | None,
                  any_live: bool) -> int:
    if any_live:
        return 60
    if next_kickoff is not None and next_kickoff - now <= timedelta(minutes=30):
        return 300
    return 21600


async def poll_once_ex(conn, clients) -> PollOutcome:
    out = PollOutcome()
    for c in clients:
        try:
            results = await c.fetch()
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", type(c).__name__, e)
            continue
        for r in results:
            res = apply_result_ex(conn, r)
            if res.newly_finished:
                out.finished.append(r.match_id)
            elif res.goal_scored:
                out.goals.append(r.match_id)
    return out


async def poll_once(conn, clients) -> list[str]:
    """Back-compat: just the newly-finished match ids."""
    return (await poll_once_ex(conn, clients)).finished


async def run_poller(conn, clients, on_finished, stop_event,
                     on_goal=None) -> None:
    while not stop_event.is_set():
        try:
            out = await poll_once_ex(conn, clients)
            if out.finished:
                await on_finished(out.finished)
            if out.goals and on_goal is not None:
                await on_goal(out.goals)
            any_live = conn.execute(
                "SELECT 1 FROM matches WHERE status='LIVE' LIMIT 1"
            ).fetchone() is not None
            nk = conn.execute(
                "SELECT MIN(kickoff_time) k FROM matches WHERE status='SCHEDULED'"
            ).fetchone()["k"]
            next_kickoff = None
            if nk:
                try:
                    next_kickoff = datetime.fromisoformat(
                        nk.replace("Z", "+00:00"))
                except ValueError:
                    next_kickoff = None
            delay = poll_interval(datetime.now().astimezone(),
                                  next_kickoff, any_live)
        except Exception as e:  # noqa: BLE001
            log.exception("poll cycle error: %s", e)
            delay = 300
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
