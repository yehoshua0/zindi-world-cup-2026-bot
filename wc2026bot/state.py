import sqlite3
from dataclasses import dataclass

STAGE_ORDINAL: dict[str, int] = {
    "group": 1, "roundof32": 2, "roundof16": 3, "qf": 4,
    "sf": 5, "runnerup": 6, "champion": 7,
}
ORDINAL_STAGE: dict[int, str] = {v: k for k, v in STAGE_ORDINAL.items()}

# A knockout match at stage X means both teams *reached* stage X.
MATCH_STAGE_TO_REACHED = {
    "group": "group",
    "roundof32": "roundof32",
    "roundof16": "roundof16",
    "qf": "qf",
    "sf": "sf",
    "final": "runnerup",  # reaching the final = at least runnerup
}


@dataclass(frozen=True)
class MatchResult:
    match_id: str
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    status: str  # SCHEDULED | LIVE | FINISHED
    match_stage: str
    kickoff_time: str


def recompute_team_goals(conn: sqlite3.Connection, team_id: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN home_team_id=? THEN home_score
                                 WHEN away_team_id=? THEN away_score END), 0) g
        FROM matches
        WHERE status='FINISHED' AND (home_team_id=? OR away_team_id=?)
        """,
        (team_id, team_id, team_id, team_id),
    ).fetchone()
    g = int(row["g"])
    conn.execute("UPDATE teams_state SET actual_goals=? WHERE team_id=?",
                 (g, team_id))
    return g


def advance_stage(conn: sqlite3.Connection, team_id: str, new_stage: str) -> None:
    cur = conn.execute(
        "SELECT current_stage FROM teams_state WHERE team_id=?",
        (team_id,)).fetchone()
    if cur is None:
        return
    if new_stage not in STAGE_ORDINAL or cur["current_stage"] not in STAGE_ORDINAL:
        return
    if STAGE_ORDINAL[new_stage] > STAGE_ORDINAL[cur["current_stage"]]:
        conn.execute("UPDATE teams_state SET current_stage=? WHERE team_id=?",
                     (new_stage, team_id))


def apply_result(conn: sqlite3.Connection, r: MatchResult) -> bool:
    prev = conn.execute("SELECT status FROM matches WHERE match_id=?",
                        (r.match_id,)).fetchone()
    prev_status = prev["status"] if prev else None
    conn.execute(
        """
        INSERT INTO matches(match_id, home_team_id, away_team_id, home_score,
                            away_score, status, match_stage, kickoff_time)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(match_id) DO UPDATE SET
            home_score=excluded.home_score,
            away_score=excluded.away_score,
            status=excluded.status
        """,
        (r.match_id, r.home_team_id, r.away_team_id, r.home_score,
         r.away_score, r.status, r.match_stage, r.kickoff_time),
    )
    newly_finished = r.status == "FINISHED" and prev_status != "FINISHED"
    if newly_finished:
        for tid in (r.home_team_id, r.away_team_id):
            recompute_team_goals(conn, tid)
        reached = MATCH_STAGE_TO_REACHED.get(r.match_stage, r.match_stage)
        advance_stage(conn, r.home_team_id, reached)
        advance_stage(conn, r.away_team_id, reached)
    conn.commit()
    return newly_finished
