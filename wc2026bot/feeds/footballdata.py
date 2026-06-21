import asyncio
import httpx
import logging
from dataclasses import dataclass
from wc2026bot.state import MatchResult, make_match_id
from wc2026bot.teams import Team

log = logging.getLogger(__name__)
BASE = "https://api.football-data.org/v4/competitions/WC"
URL = f"{BASE}/matches"
SCORERS_URL = f"{BASE}/scorers"
STANDINGS_URL = f"{BASE}/standings"
SEASON = 2026  # starting year of the edition; pins the query against drift


@dataclass(frozen=True)
class Scorer:
    name: str
    team: str
    goals: int


@dataclass(frozen=True)
class StandingRow:
    position: int
    team: str
    played: int
    points: int
    goal_diff: int
    goals_for: int


@dataclass(frozen=True)
class GroupTable:
    group: str
    rows: list[StandingRow]
STATUS_MAP = {
    "SCHEDULED": "SCHEDULED", "TIMED": "SCHEDULED", "IN_PLAY": "LIVE",
    "PAUSED": "LIVE", "FINISHED": "FINISHED",
}


class FootballDataClient:
    def __init__(self, teams_by_fd: dict[str, Team], http: httpx.AsyncClient,
                 api_key: str | None) -> None:
        self._teams = teams_by_fd
        self._http = http
        self._key = api_key

    async def fetch(self) -> list[MatchResult]:
        if not self._key:
            return []
        headers = {"X-Auth-Token": self._key}
        params = {"season": SEASON}
        resp = await self._http.get(URL, headers=headers, params=params)
        # Football-Data throttles on the free tier; honor Retry-After once.
        if resp.status_code == 429:
            retry = resp.headers.get("Retry-After", "60")
            retry_s = int(retry) if str(retry).isdigit() else 60
            log.warning("fd: rate limited, retrying after %ss", retry_s)
            await asyncio.sleep(retry_s)
            resp = await self._http.get(URL, headers=headers, params=params)
        resp.raise_for_status()
        remaining = resp.headers.get("X-Requests-Available-Minute")
        if remaining is not None and str(remaining).isdigit() and int(remaining) <= 1:
            log.info("fd: throttle low, %s request(s) left this minute", remaining)
        out: list[MatchResult] = []
        for m in resp.json().get("matches", []):
            home = self._teams.get(m["homeTeam"].get("name", ""))
            away = self._teams.get(m["awayTeam"].get("name", ""))
            if home is None or away is None:
                log.info("fd: skip unmapped match %s", m.get("id"))
                continue
            ft = m.get("score", {}).get("fullTime", {})
            hs = ft.get("home") or 0
            as_ = ft.get("away") or 0
            kickoff = m.get("utcDate", "")
            winner_code = m.get("score", {}).get("winner")
            winner = None
            if winner_code == "HOME_TEAM":
                winner = home.zindi_id
            elif winner_code == "AWAY_TEAM":
                winner = away.zindi_id
            out.append(MatchResult(
                match_id=make_match_id(home.zindi_id, away.zindi_id, kickoff),
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=hs, away_score=as_,
                status=STATUS_MAP.get(m.get("status", ""), "SCHEDULED"),
                match_stage=_fd_stage(m.get("stage", "")),
                kickoff_time=kickoff,
                winner_team_id=winner))
        return out


    async def fetch_scorers(self, limit: int = 10) -> list[Scorer]:
        if not self._key:
            return []
        resp = await self._http.get(
            SCORERS_URL, headers={"X-Auth-Token": self._key},
            params={"season": SEASON, "limit": limit})
        resp.raise_for_status()
        out: list[Scorer] = []
        for s in resp.json().get("scorers", []):
            out.append(Scorer(
                name=s.get("player", {}).get("name", "?"),
                team=s.get("team", {}).get("name", "?"),
                goals=int(s.get("goals") or 0)))
        return out

    async def fetch_standings(self) -> list[GroupTable]:
        if not self._key:
            return []
        resp = await self._http.get(
            STANDINGS_URL, headers={"X-Auth-Token": self._key},
            params={"season": SEASON})
        resp.raise_for_status()
        groups: list[GroupTable] = []
        for g in resp.json().get("standings", []):
            if g.get("type") not in (None, "TOTAL"):
                continue  # skip HOME/AWAY splits, keep overall table only
            rows = [StandingRow(
                position=int(t.get("position") or 0),
                team=t.get("team", {}).get("name", "?"),
                played=int(t.get("playedGames") or 0),
                points=int(t.get("points") or 0),
                goal_diff=int(t.get("goalDifference") or 0),
                goals_for=int(t.get("goalsFor") or 0),
            ) for t in g.get("table", [])]
            groups.append(GroupTable(group=g.get("group") or "", rows=rows))
        return groups


def _fd_stage(stage: str) -> str:
    return {
        "GROUP_STAGE": "group", "LAST_32": "roundof32",
        "LAST_16": "roundof16", "QUARTER_FINALS": "qf",
        "SEMI_FINALS": "sf", "THIRD_PLACE": "sf", "FINAL": "final",
    }.get(stage, "unknown")
