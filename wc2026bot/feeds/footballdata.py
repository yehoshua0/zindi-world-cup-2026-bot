import httpx
import logging
from wc2026bot.state import MatchResult
from wc2026bot.teams import Team

log = logging.getLogger(__name__)
URL = "https://api.football-data.org/v4/competitions/WC/matches"
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
        resp = await self._http.get(URL, headers=headers)
        resp.raise_for_status()
        out: list[MatchResult] = []
        for m in resp.json().get("matches", []):
            home = self._teams.get(m["homeTeam"].get("name", ""))
            away = self._teams.get(m["awayTeam"].get("name", ""))
            if home is None or away is None:
                log.info("fd: skip unmapped match %s", m.get("id"))
                continue
            ft = m.get("score", {}).get("fullTime", {})
            out.append(MatchResult(
                match_id=f"fd-{m['id']}",
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=ft.get("home") or 0, away_score=ft.get("away") or 0,
                status=STATUS_MAP.get(m.get("status", ""), "SCHEDULED"),
                match_stage=_fd_stage(m.get("stage", "")),
                kickoff_time=m.get("utcDate", "")))
        return out


def _fd_stage(stage: str) -> str:
    return {
        "GROUP_STAGE": "group", "LAST_32": "roundof32",
        "LAST_16": "roundof16", "QUARTER_FINALS": "qf",
        "SEMI_FINALS": "sf", "FINAL": "final",
    }.get(stage, "group")
