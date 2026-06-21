# Stats Tracking — Design Spec
Date: 2026-06-21

## Goal

Instrument the bot to capture enough data for a sharp post-mortem publication (target: end of July 2026) covering adoption funnel, engagement, leaderboard dynamics, and notification delivery.

## Schema additions (`db.py`)

### `events` table
```sql
CREATE TABLE IF NOT EXISTS events (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id  INTEGER,          -- NULL for system events (e.g. snapshot)
  event    TEXT NOT NULL,    -- see event catalogue below
  ts       TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(ts);
```

### `leaderboard_snapshots` table
```sql
CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
  snapshot_date TEXT NOT NULL,
  user_id       INTEGER NOT NULL,
  rank          INTEGER NOT NULL,
  combined      REAL NOT NULL,
  rmse          REAL NOT NULL,
  f1            REAL NOT NULL,
  PRIMARY KEY (snapshot_date, user_id)
);
```

## Event catalogue

| event | trigger |
|---|---|
| `start` | /start |
| `help` | /help |
| `setname_ok` | /setname success |
| `setname_fail` | /setname — name taken or invalid |
| `upload_prompt` | /upload command (no file) |
| `upload_ok` | CSV accepted and stored |
| `upload_fail` | CSV rejected (ValidationError) |
| `cmd_me` | /me |
| `cmd_rank` | /rank |
| `cmd_today` | /today |
| `cmd_yesterday` | /yesterday |
| `cmd_team` | /team |
| `cmd_scorers` | /scorers |
| `cmd_standings` | /standings |
| `notify_goal_ok` | push sent (goal event) |
| `notify_goal_fail` | push failed (goal event) |
| `notify_finish_ok` | push sent (match finish) |
| `notify_finish_fail` | push failed (match finish) |
| `leaderboard_snapshot` | daily snapshot written (chat_id NULL) |

## New functions

### `db.log_event(conn, event, chat_id=None)`
Single INSERT into `events`. Fire-and-forget; never raises.

### `db.snapshot_leaderboard(conn)`
Reads `cohort_scores()` + `user_metrics()` per user, inserts a row per user into `leaderboard_snapshots` for today's date (ISO). Skips if snapshot for today already exists (idempotent). Logs `leaderboard_snapshot` event.

## Integration points

### `main.py` — command handlers
Each handler calls `db.log_event(conn, "<event>", chat_id)` immediately after the primary action (or on failure path). No behaviour change — logging is additive.

### `main.py` — `_push()` helper
Log `notify_{kind}_ok` per successful `send_message`, `notify_{kind}_fail` per exception. `chat_id` = the recipient's Telegram chat id.

### `main.py` — daily snapshot task
New coroutine `run_daily_snapshot(conn, stop_event)` runs in parallel with the poller. Sleeps until midnight UTC, calls `db.snapshot_leaderboard(conn)`, repeats. Launched as a second `asyncio.create_task` in `_run()`.

## Stats derivable post-hoc

| Metric | Query |
|---|---|
| Funnel conversion | COUNT distinct chat_ids per event: start → setname_ok → upload_ok |
| Re-upload rate | COUNT upload_ok per chat_id where count > 1 |
| DAU | COUNT DISTINCT chat_id per day from events |
| Command popularity | COUNT(*) GROUP BY event WHERE event LIKE 'cmd_%' |
| Notification delivery rate | notify_*_ok / (notify_*_ok + notify_*_fail) |
| Leaderboard volatility | stddev(rank delta) per snapshot_date from leaderboard_snapshots |
| Rank trajectory | SELECT * FROM leaderboard_snapshots WHERE user_id=? ORDER BY snapshot_date |

## Out of scope

- No metrics dashboard / export command
- No aggregation tables (raw events are enough for post-hoc analysis)
- No user-facing stats beyond existing /me and /rank
