import sqlite3

from wc2026bot.notify import cohort_scores, user_metrics
from wc2026bot.validation import ParsedRow


def cmd_start_text() -> str:
    return (
        "⚽ WC2026 Live Tracker\n\n"
        "/upload — send your submission CSV (reply with the file)\n"
        "/me — your live RMSE, F1, rank\n"
        "/rank — leaderboard\n"
        "/today — today's matches\n"
        "/team <ISO3> — a team's status\n"
        "/help — this message")


def register_user(conn: sqlite3.Connection, chat_id: int) -> int:
    conn.execute(
        "INSERT OR IGNORE INTO users(telegram_chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    return conn.execute(
        "SELECT user_id FROM users WHERE telegram_chat_id=?",
        (chat_id,)).fetchone()["user_id"]


def _user_id(conn: sqlite3.Connection, chat_id: int) -> int | None:
    r = conn.execute("SELECT user_id FROM users WHERE telegram_chat_id=?",
                     (chat_id,)).fetchone()
    return r["user_id"] if r else None


def store_submission(conn: sqlite3.Connection, chat_id: int,
                     rows: list[ParsedRow], file_hash: str) -> None:
    uid = register_user(conn, chat_id)
    conn.execute("UPDATE submissions SET is_active=0 WHERE user_id=?", (uid,))
    cur = conn.execute(
        "INSERT INTO submissions(user_id, file_hash, is_active) VALUES (?,?,1)",
        (uid, file_hash))
    sid = cur.lastrowid
    conn.executemany(
        "INSERT INTO predictions(submission_id, team_id, predicted_goals, "
        "predicted_stage) VALUES (?,?,?,?)",
        [(sid, r.team_id, r.total_goals, r.target) for r in rows])
    conn.commit()


def _active_submission(conn: sqlite3.Connection, chat_id: int) -> int | None:
    uid = _user_id(conn, chat_id)
    if uid is None:
        return None
    r = conn.execute(
        "SELECT submission_id FROM submissions WHERE user_id=? AND is_active=1",
        (uid,)).fetchone()
    return r["submission_id"] if r else None


def me_text(conn: sqlite3.Connection, chat_id: int) -> str:
    sid = _active_submission(conn, chat_id)
    if sid is None:
        return "No active submission. Use /upload first."
    raw_rmse, f1 = user_metrics(conn, sid)
    rank = next((u.rank for u in cohort_scores(conn)
                 if u.user_id == _user_id(conn, chat_id)), None)
    return (f"📊 Your live standing\n"
            f"RMSE (goals so far): {raw_rmse:.3f}\n"
            f"Macro F1 (stage so far): {f1:.3f}\n"
            f"Rank: {rank if rank else '-'}")


def rank_text(conn: sqlite3.Connection, top: int = 10) -> str:
    scores = cohort_scores(conn)
    if not scores:
        return "No submissions yet."
    lines = ["🏆 Leaderboard (live)"]
    for u in scores[:top]:
        lines.append(f"{u.rank}. user {u.user_id} — "
                     f"score {u.combined:.3f} (F1 {u.f1:.3f})")
    return "\n".join(lines)


def team_text(conn: sqlite3.Connection, chat_id: int, iso3: str,
              team_names: dict[str, str]) -> str:
    tid = f"WC-2026_{iso3.upper()}"
    r = conn.execute(
        "SELECT country, actual_goals, current_stage FROM teams_state "
        "WHERE team_id=?", (tid,)).fetchone()
    if r is None:
        return f"Unknown team '{iso3}'."
    base = (f"{r['country']}: {r['actual_goals']} goals so far, "
            f"reached {r['current_stage']}")
    sid = _active_submission(conn, chat_id)
    if sid:
        p = conn.execute(
            "SELECT predicted_goals, predicted_stage FROM predictions "
            "WHERE submission_id=? AND team_id=?", (sid, tid)).fetchone()
        if p:
            base += (f"\nYour pick: {p['predicted_goals']:.1f} goals, "
                     f"{p['predicted_stage']}")
    return base
