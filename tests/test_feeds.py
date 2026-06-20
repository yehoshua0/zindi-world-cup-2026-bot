import asyncio
import pytest
from wc2026bot.teams import load_teams, by_fd_name, by_espn_name
from wc2026bot.feeds.espn import EspnClient
from wc2026bot.feeds.footballdata import FootballDataClient
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

class FakeRespHdr:
    def __init__(self, payload, status=200, headers=None):
        self._p = payload
        self.status_code = status
        self.headers = headers or {}
    def raise_for_status(self): pass
    def json(self): return self._p

class FakeHttpSeq:
    """Returns queued responses in order, one per get() call."""
    def __init__(self, responses): self._r = list(responses)
    async def get(self, url, **kw): return self._r.pop(0)

FD_SAMPLE = {"matches": [{
    "id": 1, "status": "FINISHED", "utcDate": "2026-06-15T18:00:00Z",
    "stage": "QUARTER_FINALS",
    "homeTeam": {"name": "Austria"}, "awayTeam": {"name": "Belgium"},
    "score": {"fullTime": {"home": 2, "away": 1}, "winner": "HOME_TEAM"},
}]}

def test_fd_maps_match_with_stage_and_winner():
    teams = load_teams("data/teams.csv")
    http = FakeHttpSeq([FakeRespHdr(FD_SAMPLE, headers={"X-Requests-Available-Minute": "9"})])
    client = FootballDataClient(by_fd_name(teams), http, api_key="k")
    res = asyncio.run(client.fetch())
    assert len(res) == 1
    m = res[0]
    assert m.match_stage == "qf"
    assert m.winner_team_id == "WC-2026_AUT"
    assert (m.home_score, m.away_score) == (2, 1)

def test_fd_retries_on_429_then_succeeds():
    teams = load_teams("data/teams.csv")
    http = FakeHttpSeq([
        FakeRespHdr({}, status=429, headers={"Retry-After": "0"}),
        FakeRespHdr(FD_SAMPLE, headers={"X-Requests-Available-Minute": "0"}),
    ])
    client = FootballDataClient(by_fd_name(teams), http, api_key="k")
    res = asyncio.run(client.fetch())
    assert len(res) == 1  # recovered after honoring Retry-After

def test_fd_no_key_returns_empty():
    teams = load_teams("data/teams.csv")
    client = FootballDataClient(by_fd_name(teams), FakeHttpSeq([]), api_key=None)
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
