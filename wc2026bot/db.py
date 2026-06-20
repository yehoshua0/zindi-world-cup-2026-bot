import sqlite3
from wc2026bot.teams import Team

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  telegram_chat_id INTEGER UNIQUE NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);
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
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def seed_teams(conn: sqlite3.Connection, teams: dict[str, Team]) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO teams_state(team_id, country, iso3) VALUES (?,?,?)",
        [(t.zindi_id, t.country, t.iso3) for t in teams.values()],
    )
    conn.commit()
