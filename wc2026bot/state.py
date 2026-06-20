import sqlite3
from dataclasses import dataclass

STAGE_ORDINAL: dict[str, int] = {
    "group": 1, "roundof32": 2, "roundof16": 3, "qf": 4,
    "sf": 5, "runnerup": 6, "champion": 7,
}
ORDINAL_STAGE: dict[int, str] = {v: k for k, v in STAGE_ORDINAL.items()}

# Non-final knockout match at stage X means both teams *reached* stage X.
# 'final' is handled separately (winner -> champion, loser -> runnerup).
MATCH_STAGE_TO_REACHED = {
    "group": "group",
    "roundof32": "roundof32",
    "roundof16": "roundof16",
    "qf": "qf",
    "sf": "sf",
}


@dataclass(frozen=True)
class MatchResult:
    match_id: str
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    status: str  # SCHEDULED | LIVE | FINISHED
    match_stage: str  # 'unknown' when a source can't label the round
    kickoff_time: str
    winner_team_id: str | None = None


def make_match_id(home_id: str, away_id: str, kickoff_time: str) -> str:
    lo, hi = sorted([home_id, away_id])
    date10 = (kickoff_time or "")[:10]
    return f"{lo}__{hi}__{date10}"


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
    # Stage precedence: a known stage is never overwritten by 'unknown'.
    # kickoff: keep existing if the new value is empty.
    conn.execute(
        """
        INSERT INTO matches(match_id, home_team_id, away_team_id, home_score,
                            away_score, status, match_stage, kickoff_time)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(match_id) DO UPDATE SET
            home_score=excluded.home_score,
            away_score=excluded.away_score,
            status=excluded.status,
            match_stage=CASE WHEN excluded.match_stage != 'unknown'
                             THEN excluded.match_stage ELSE matches.match_stage END,
            kickoff_time=CASE WHEN excluded.kickoff_time != ''
                              THEN excluded.kickoff_time ELSE matches.kickoff_time END
        """,
        (r.match_id, r.home_team_id, r.away_team_id, r.home_score,
         r.away_score, r.status, r.match_stage, r.kickoff_time),
    )
    newly_finished = r.status == "FINISHED" and prev_status != "FINISHED"
    if r.status == "FINISHED":
        # Read the authoritative (post-precedence) stage from the stored row.
        row = conn.execute(
            "SELECT match_stage FROM matches WHERE match_id=?",
            (r.match_id,)).fetchone()
        eff_stage = row["match_stage"] if row else r.match_stage
        for tid in (r.home_team_id, r.away_team_id):
            recompute_team_goals(conn, tid)
        if eff_stage == "final":
            winner = r.winner_team_id
            if winner is None:
                if r.home_score > r.away_score:
                    winner = r.home_team_id
                elif r.away_score > r.home_score:
                    winner = r.away_team_id
            if winner is not None:
                loser = (r.away_team_id if winner == r.home_team_id
                         else r.home_team_id)
                advance_stage(conn, winner, "champion")
                advance_stage(conn, loser, "runnerup")
            else:
                # Winner not yet known (e.g. drawn, awaiting PK result).
                # Forward-only guard means this never downgrades a champion
                # already set by an authoritative source.
                advance_stage(conn, r.home_team_id, "runnerup")
                advance_stage(conn, r.away_team_id, "runnerup")
        elif eff_stage in MATCH_STAGE_TO_REACHED:
            reached = MATCH_STAGE_TO_REACHED[eff_stage]
            advance_stage(conn, r.home_team_id, reached)
            advance_stage(conn, r.away_team_id, reached)
        # eff_stage == 'unknown': goals updated, stage left for an
        # authoritative source to supply later.
    conn.commit()
    return newly_finished
