import httpx
import logging
from wc2026bot.state import MatchResult, make_match_id
from wc2026bot.teams import Team

log = logging.getLogger(__name__)
URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
       "fifa.world/scoreboard")
STATE_MAP = {"pre": "SCHEDULED", "in": "LIVE", "post": "FINISHED"}
# ESPN exposes the round as event.season.slug, e.g. "group-stage".
STAGE_SLUG_MAP = {
    "group-stage": "group",
    "round-of-32": "roundof32",
    "round-of-16": "roundof16",
    "quarterfinals": "qf",
    "semifinals": "sf",
    "3rd-place": "sf", "third-place": "sf",
    "final": "final",
}


def _espn_stage(season: dict) -> str:
    slug = (season or {}).get("slug", "")
    return STAGE_SLUG_MAP.get(slug, "unknown")


class EspnClient:
    def __init__(self, teams_by_espn: dict[str, Team], http: httpx.AsyncClient) -> None:
        self._teams = teams_by_espn
        self._http = http

    async def fetch(self) -> list[MatchResult]:
        resp = await self._http.get(URL)
        resp.raise_for_status()
        out: list[MatchResult] = []
        for ev in resp.json().get("events", []):
            comp = ev["competitions"][0]
            home = away = None
            hs = as_ = 0
            for c in comp["competitors"]:
                t = self._teams.get(c["team"]["displayName"])
                if c["homeAway"] == "home":
                    home, hs = t, int(c["score"])
                else:
                    away, as_ = t, int(c["score"])
            if home is None or away is None:
                log.info("espn: skip unmapped match %s", ev.get("id"))
                continue
            status = STATE_MAP.get(
                ev["status"]["type"]["state"], "SCHEDULED")
            kickoff = ev.get("date", "")
            winner = None
            if hs > as_:
                winner = home.zindi_id
            elif as_ > hs:
                winner = away.zindi_id
            if status != "FINISHED":
                winner = None
            out.append(MatchResult(
                match_id=make_match_id(home.zindi_id, away.zindi_id, kickoff),
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=hs, away_score=as_, status=status,
                match_stage=_espn_stage(ev.get("season", {})),
                kickoff_time=kickoff,
                winner_team_id=winner))
        return out
