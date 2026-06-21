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


def _affected_user_rows(conn: sqlite3.Connection, match_id: str):
    """(user_id, chat_id, submission_id) for named, active submissions that
    reference either team in the match."""
    m = conn.execute(
        "SELECT home_team_id, away_team_id FROM matches WHERE match_id=?",
        (match_id,)).fetchone()
    if m is None:
        return []
    return conn.execute(
        """
        SELECT DISTINCT u.user_id uid, u.telegram_chat_id cid,
                        s.submission_id sid
        FROM predictions p
        JOIN submissions s ON s.submission_id=p.submission_id AND s.is_active=1
        JOIN users u ON u.user_id=s.user_id
        WHERE p.team_id IN (?, ?)
        """,
        (m["home_team_id"], m["away_team_id"]),
    ).fetchall()


def _team_line(conn: sqlite3.Connection, sid: int, team_id: str,
               name: str) -> str:
    p = conn.execute(
        "SELECT predicted_goals, predicted_stage FROM predictions "
        "WHERE submission_id=? AND team_id=?", (sid, team_id)).fetchone()
    st = conn.execute(
        "SELECT actual_goals, current_stage FROM teams_state WHERE team_id=?",
        (team_id,)).fetchone()
    pick = (f"pick {p['predicted_goals']:.1f} goals/{p['predicted_stage']}"
            if p else "no pick")
    now = f"now {st['actual_goals']} goals/{st['current_stage']}" if st else "-"
    return f"• {name}: {pick} ({now})"


def personalized_messages(conn: sqlite3.Connection, match_id: str,
                          team_names: dict[str, str],
                          kind: str = "finish") -> list[tuple[int, str]]:
    """One (chat_id, text) per affected user, with their picks vs reality,
    live rank and the cohort-average score."""
    m = conn.execute(
        "SELECT home_team_id, away_team_id, home_score, away_score "
        "FROM matches WHERE match_id=?", (match_id,)).fetchone()
    if m is None:
        return []
    rows = _affected_user_rows(conn, match_id)
    if not rows:
        return []
    h, a = m["home_team_id"], m["away_team_id"]
    hn = team_names.get(h, h)
    an = team_names.get(a, a)
    header = "⚽ GOAL" if kind == "goal" else "🏁 FULL TIME"
    score = f"{hn} {m['home_score']} - {m['away_score']} {an}"
    scores = {u.user_id: u for u in cohort_scores(conn)}
    avg = (sum(u.combined for u in scores.values()) / len(scores)
           if scores else 0.0)
    out: list[tuple[int, str]] = []
    for r in rows:
        u = scores.get(r["uid"])
        rank_line = (
            f"Your rank: {u.rank}/{len(scores)} · score {u.combined:.3f} "
            f"(cohort avg {avg:.3f})" if u else "Your rank: -")
        text = "\n".join([
            f"{header} — {score}",
            _team_line(conn, r["sid"], h, hn),
            _team_line(conn, r["sid"], a, an),
            rank_line,
        ])
        out.append((r["cid"], text))
    return out
