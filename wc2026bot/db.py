import sqlite3
from wc2026bot.teams import Team

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_chat_id INTEGER UNIQUE NOT NULL,
  display_name TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
-- Unique display names (case-insensitive); multiple NULLs allowed by SQLite.
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_name
  ON users(display_name COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS submissions (
  submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  file_hash TEXT NOT NULL,
  uploaded_at TEXT DEFAULT (datetime('now')),
  is_active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS teams_state (
  team_id TEXT PRIMARY KEY,
  country TEXT NOT NULL,
  iso3 TEXT NOT NULL,
  actual_goals INTEGER DEFAULT 0,
  current_stage TEXT DEFAULT 'group'
);
CREATE TABLE IF NOT EXISTS predictions (
  prediction_id INTEGER PRIMARY KEY AUTOINCREMENT,
  submission_id INTEGER NOT NULL REFERENCES submissions(submission_id) ON DELETE CASCADE,
  team_id TEXT NOT NULL REFERENCES teams_state(team_id),
  predicted_goals REAL NOT NULL,
  predicted_stage TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
  match_id TEXT PRIMARY KEY,
  home_team_id TEXT REFERENCES teams_state(team_id),
  away_team_id TEXT REFERENCES teams_state(team_id),
  home_score INTEGER DEFAULT 0,
  away_score INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'SCHEDULED',
  match_stage TEXT NOT NULL,
  kickoff_time TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pred_sub ON predictions(submission_id);
CREATE INDEX IF NOT EXISTS idx_teams_stage ON teams_state(current_stage);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER,
  event   TEXT NOT NULL,
  ts      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(ts);
CREATE TABLE IF NOT EXISTS web_feedback (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
  lang   TEXT    DEFAULT 'en',
  ts     TEXT    DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
  snapshot_date TEXT NOT NULL,
  user_id       INTEGER NOT NULL,
  rank          INTEGER NOT NULL,
  combined      REAL NOT NULL,
  rmse          REAL NOT NULL,
  f1            REAL NOT NULL,
  PRIMARY KEY (snapshot_date, user_id)
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    # Migration: add display_name to a pre-existing users table (no-op if present).
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
    if cols and "display_name" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    conn.executescript(SCHEMA)
    conn.commit()


def seed_teams(conn: sqlite3.Connection, teams: dict[str, Team]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO teams_state(team_id, country, iso3) VALUES (?,?,?)",
        [(t.zindi_id, t.country, t.iso3) for t in teams.values()],
    )
    conn.commit()


def log_event(conn: sqlite3.Connection, event: str,
              chat_id: int | None = None) -> None:
    try:
        conn.execute(
            "INSERT INTO events(event, chat_id) VALUES (?,?)", (event, chat_id))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def snapshot_leaderboard(conn: sqlite3.Connection) -> int:
    from datetime import datetime, timezone
    from wc2026bot.notify import cohort_scores, user_metrics
    today = datetime.now(timezone.utc).date().isoformat()
    exists = conn.execute(
        "SELECT 1 FROM leaderboard_snapshots WHERE snapshot_date=? LIMIT 1",
        (today,)).fetchone()
    if exists:
        return 0
    scores = cohort_scores(conn)
    if not scores:
        return 0
    subs = {r["user_id"]: r["submission_id"] for r in conn.execute(
        "SELECT user_id, submission_id FROM submissions WHERE is_active=1")}
    rows = []
    for u in scores:
        sid = subs.get(u.user_id)
        if sid is None:
            continue
        rmse_val, f1_val = user_metrics(conn, sid)
        rows.append((today, u.user_id, u.rank, u.combined, rmse_val, f1_val))
    if not rows:
        return 0
    conn.executemany(
        "INSERT OR IGNORE INTO leaderboard_snapshots"
        "(snapshot_date, user_id, rank, combined, rmse, f1) VALUES (?,?,?,?,?,?)",
        rows)
    conn.commit()
    return len(rows)
