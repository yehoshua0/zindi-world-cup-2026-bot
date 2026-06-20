import asyncio
from datetime import datetime, timedelta, timezone
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.state import MatchResult
from wc2026bot.poller import poll_interval, poll_once

def test_intervals():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert poll_interval(now, None, any_live=True) == 60
    soon = now + timedelta(minutes=10)
    assert poll_interval(now, soon, any_live=False) == 300
    far = now + timedelta(hours=10)
    assert poll_interval(now, far, any_live=False) == 21600

def test_poll_once_returns_newly_finished():
    c = connect(":memory:"); init_db(c); seed_teams(c, load_teams("data/teams.csv"))
    class Client:
        def __init__(self, status): self.status = status
        async def fetch(self):
            return [MatchResult("espn-1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                    self.status, "group", "2026-06-15T18:00:00Z")]
    # first cycle: live -> no finishes
    assert asyncio.run(poll_once(c, [Client("LIVE")])) == []
    # second cycle: finished -> one finish
    assert asyncio.run(poll_once(c, [Client("FINISHED")])) == ["espn-1"]
    # third cycle: still finished -> idempotent, no new finish
    assert asyncio.run(poll_once(c, [Client("FINISHED")])) == []
