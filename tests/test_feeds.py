import asyncio
import pytest
from wc2026bot.teams import load_teams, by_espn_name
from wc2026bot.feeds.espn import EspnClient
from wc2026bot.feeds.base import fetch_with_fallback

class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p

class FakeHttp:
    def __init__(self, payload): self._p = payload
    async def get(self, url, **kw): return FakeResp(self._p)

ESPN_SAMPLE = {
  "events": [{
    "id": "401",
    "status": {"type": {"state": "post"}},
    "competitions": [{"competitors": [
      {"homeAway": "home", "score": "2", "team": {"displayName": "Austria"}},
      {"homeAway": "away", "score": "1", "team": {"displayName": "Belgium"}},
    ]}]
  }]
}

def test_espn_maps_finished_match():
    teams = load_teams("data/teams.csv")
    client = EspnClient(by_espn_name(teams), FakeHttp(ESPN_SAMPLE))
    res = asyncio.run(client.fetch())
    assert len(res) == 1
    m = res[0]
    assert m.home_team_id == "WC-2026_AUT"
    assert m.away_team_id == "WC-2026_BEL"
    assert (m.home_score, m.away_score) == (2, 1)
    assert m.status == "FINISHED"

def test_espn_skips_unknown_team():
    teams = load_teams("data/teams.csv")
    bad = {"events": [{"id": "9", "status": {"type": {"state": "post"}},
        "competitions": [{"competitors": [
          {"homeAway": "home", "score": "0", "team": {"displayName": "Narnia"}},
          {"homeAway": "away", "score": "0", "team": {"displayName": "Belgium"}},
        ]}]}]}
    client = EspnClient(by_espn_name(teams), FakeHttp(bad))
    assert asyncio.run(client.fetch()) == []

def test_fallback_uses_second_on_empty():
    class Empty:
        async def fetch(self): return []
    class Has:
        async def fetch(self):
            from wc2026bot.state import MatchResult
            return [MatchResult("m", "WC-2026_AUT", "WC-2026_BEL", 0, 0,
                    "SCHEDULED", "group", "2026-06-15T18:00:00Z")]
    res = asyncio.run(fetch_with_fallback([Empty(), Has()]))
    assert len(res) == 1
