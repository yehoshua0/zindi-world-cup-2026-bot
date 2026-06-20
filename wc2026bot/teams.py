import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    zindi_id: str
    country: str
    iso3: str
    espn_name: str
    fd_name: str


def load_teams(path: str) -> dict[str, Team]:
    out: dict[str, Team] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = Team(r["zindi_id"], r["country"], r["iso3"],
                     r["espn_name"], r["fd_name"])
            out[t.zindi_id] = t
    return out


def by_espn_name(teams: dict[str, Team]) -> dict[str, Team]:
    return {t.espn_name: t for t in teams.values()}


def by_fd_name(teams: dict[str, Team]) -> dict[str, Team]:
    return {t.fd_name: t for t in teams.values()}
