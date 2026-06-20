import sqlite3

from wc2026bot.notify import cohort_scores, user_metrics
from wc2026bot.validation import ParsedRow

NAME_MIN, NAME_MAX = 2, 32


class SetNameError(Exception):
    pass


def cmd_start_text() -> str:
    return (
        "⚽ WC2026 Live Tracker\n\n"
        "First pick a name: /setname <your name>\n\n"
        "/setname <name> — set your leaderboard name (required)\n"
        "/upload — send your submission CSV (reply with the file)\n"
        "/me — your live RMSE, F1, rank\n"
        "/rank — leaderboard\n"
        "/team <ISO3> — a team's status\n"
        "/today — today's matches\n"
        "/yesterday — yesterday's matches\n"
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


def display_name(conn: sqlite3.Connection, chat_id: int) -> str | None:
    r = conn.execute("SELECT display_name FROM users WHERE telegram_chat_id=?",
                     (chat_id,)).fetchone()
    return r["display_name"] if r and r["display_name"] else None


def set_display_name(conn: sqlite3.Connection, chat_id: int, name: str) -> str:
    name = " ".join(name.split())  # collapse whitespace
    if not (NAME_MIN <= len(name) <= NAME_MAX):
        raise SetNameError(
            f"Name must be {NAME_MIN}-{NAME_MAX} characters.")
    register_user(conn, chat_id)
    taken = conn.execute(
        "SELECT 1 FROM users WHERE display_name=? COLLATE NOCASE "
        "AND telegram_chat_id<>?", (name, chat_id)).fetchone()
    if taken:
        raise SetNameError(f"Name '{name}' is already taken. Pick another.")
    conn.execute("UPDATE users SET display_name=? WHERE telegram_chat_id=?",
                 (name, chat_id))
    conn.commit()
    return name


def needs_name_msg(conn: sqlite3.Connection, chat_id: int) -> str | None:
    """Return a prompt string if the user has no name yet, else None."""
    if display_name(conn, chat_id) is None:
        return "Please set a name first: /setname <your name>"
    return None


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
    names = {r["user_id"]: r["display_name"] for r in conn.execute(
        "SELECT user_id, display_name FROM users "
        "WHERE display_name IS NOT NULL")}
    # Only named users on the board; unnamed ones never show as "user N".
    named = [u for u in cohort_scores(conn) if names.get(u.user_id)]
    if not named:
        return "No submissions yet."
    lines = ["🏆 Leaderboard (live)"]
    for u in named[:top]:
        lines.append(f"{u.rank}. {names[u.user_id]} — "
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


def matches_on_text(conn: sqlite3.Connection, date_iso: str,
                    team_names: dict[str, str], label: str) -> str:
    rows = conn.execute(
        "SELECT home_team_id, away_team_id, home_score, away_score, status, "
        "kickoff_time FROM matches WHERE substr(kickoff_time,1,10)=? "
        "ORDER BY kickoff_time", (date_iso,)).fetchall()
    if not rows:
        return f"No matches {label} ({date_iso})."
    lines = [f"📅 Matches {label} ({date_iso})"]
    for m in rows:
        h = team_names.get(m["home_team_id"], m["home_team_id"])
        a = team_names.get(m["away_team_id"], m["away_team_id"])
        if m["status"] == "SCHEDULED":
            kt = m["kickoff_time"] or ""
            t = kt[11:16] if len(kt) >= 16 else ""
            lines.append(f"⏰ {t} {h} vs {a}".rstrip())
        else:
            emoji = "🔴" if m["status"] == "LIVE" else "🏁"
            lines.append(f"{emoji} {h} {m['home_score']}-"
                         f"{m['away_score']} {a}")
    return "\n".join(lines)
