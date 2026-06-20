import sqlite3

from wc2026bot.evaluation import rmse, macro_f1, rank_cohort, UserScore


def _actuals(conn: sqlite3.Connection) -> tuple[dict[str, float], dict[str, str]]:
    goals: dict[str, float] = {}
    stage: dict[str, str] = {}
    for r in conn.execute(
            "SELECT team_id, actual_goals, current_stage FROM teams_state"):
        goals[r["team_id"]] = float(r["actual_goals"])
        stage[r["team_id"]] = r["current_stage"]
    return goals, stage


def user_metrics(conn: sqlite3.Connection, submission_id: int) -> tuple[float, float]:
    goals_a, stage_a = _actuals(conn)
    pg: dict[str, float] = {}
    ps: dict[str, str] = {}
    for r in conn.execute(
            "SELECT team_id, predicted_goals, predicted_stage "
            "FROM predictions WHERE submission_id=?", (submission_id,)):
        pg[r["team_id"]] = float(r["predicted_goals"])
        ps[r["team_id"]] = r["predicted_stage"]
    return rmse(pg, goals_a), macro_f1(ps, stage_a)


def cohort_scores(conn: sqlite3.Connection) -> list[UserScore]:
    per_user: dict[int, tuple[float, float]] = {}
    for r in conn.execute(
            "SELECT s.submission_id, s.user_id FROM submissions s "
            "WHERE s.is_active=1"):
        per_user[r["user_id"]] = user_metrics(conn, r["submission_id"])
    return rank_cohort(per_user)


def affected_users(conn: sqlite3.Connection, match_id: str) -> list[int]:
    m = conn.execute(
        "SELECT home_team_id, away_team_id FROM matches WHERE match_id=?",
        (match_id,)).fetchone()
    if m is None:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT u.telegram_chat_id cid
        FROM predictions p
        JOIN submissions s ON s.submission_id=p.submission_id AND s.is_active=1
        JOIN users u ON u.user_id=s.user_id
        WHERE p.team_id IN (?, ?)
        """,
        (m["home_team_id"], m["away_team_id"]),
    ).fetchall()
    return [r["cid"] for r in rows]


def build_finish_message(conn: sqlite3.Connection, match_id: str,
                         team_names: dict[str, str]) -> str:
    m = conn.execute(
        "SELECT home_team_id, away_team_id, home_score, away_score "
        "FROM matches WHERE match_id=?", (match_id,)).fetchone()
    h = team_names.get(m["home_team_id"], m["home_team_id"])
    a = team_names.get(m["away_team_id"], m["away_team_id"])
    return f"🏁 FINAL: {h} {m['home_score']} - {m['away_score']} {a}"
