# Stats Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `events` table + `leaderboard_snapshots` table to capture the adoption funnel, command usage, notification delivery, and daily rank history needed for a publication-quality post-mortem.

**Architecture:** Two new SQLite tables (`events`, `leaderboard_snapshots`) with two helper functions in `db.py` (`log_event`, `snapshot_leaderboard`). Every command handler in `main.py` calls `log_event` after its primary action. A new background coroutine `run_daily_snapshot` fires once per UTC day alongside the existing poller.

**Tech Stack:** Python 3.11+, SQLite (via stdlib `sqlite3`), python-telegram-bot, asyncio.

## Global Constraints

- No new dependencies — stdlib + existing packages only.
- `log_event` must never raise; it is fire-and-forget.
- `snapshot_leaderboard` is idempotent: re-running on the same UTC date is a no-op.
- All existing tests must continue to pass after every task.
- Test file for DB helpers: `tests/test_db.py`. Test file for main integration: `tests/test_stats_integration.py` (new).

---

### Task 1: Schema — add `events` and `leaderboard_snapshots` tables

**Files:**
- Modify: `wc2026bot/db.py`
- Modify: `tests/test_db.py`

**Interfaces:**
- Produces: `SCHEMA` string extended with both tables and their indexes.
- Produces: migration path: `init_db` runs the extended `SCHEMA` via `executescript`, which is idempotent (`CREATE TABLE IF NOT EXISTS`).

- [ ] **Step 1: Write the failing test**

Add at the bottom of `tests/test_db.py`:

```python
def test_events_and_snapshots_tables_exist(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_db(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "events" in tables
    assert "leaderboard_snapshots" in tables
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_db.py::test_events_and_snapshots_tables_exist -v
```
Expected: `FAILED` — `AssertionError`.

- [ ] **Step 3: Extend SCHEMA in `wc2026bot/db.py`**

Add the following SQL block to the end of the `SCHEMA` string (before the closing `"""`):

```python
CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id INTEGER,
  event   TEXT NOT NULL,
  ts      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_ts    ON events(ts);
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

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/test_db.py -v
```
Expected: all pass including the new test.

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/db.py tests/test_db.py
git commit -m "feat: add events and leaderboard_snapshots schema"
```

---

### Task 2: `log_event` and `snapshot_leaderboard` helpers

**Files:**
- Modify: `wc2026bot/db.py`
- Create: `tests/test_stats_integration.py`

**Interfaces:**
- Consumes: `events` and `leaderboard_snapshots` tables (Task 1).
- Consumes: `cohort_scores(conn) -> list[UserScore]` from `wc2026bot/notify.py`.
- Consumes: `user_metrics(conn, submission_id) -> tuple[float, float]` from `wc2026bot/notify.py`.
- Produces: `log_event(conn: sqlite3.Connection, event: str, chat_id: int | None = None) -> None`
- Produces: `snapshot_leaderboard(conn: sqlite3.Connection) -> int` — returns count of rows inserted (0 if today already snapshotted).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_stats_integration.py`:

```python
import hashlib
import pytest
from wc2026bot.db import connect, init_db, seed_teams, log_event, snapshot_leaderboard
from wc2026bot.teams import load_teams
from wc2026bot.validation import parse_submission
from wc2026bot.handlers import store_submission, set_display_name


def _conn():
    c = connect(":memory:")
    init_db(c)
    seed_teams(c, load_teams("data/teams.csv"))
    return c


def _full_csv():
    teams = load_teams("data/teams.csv")
    lines = ["ID,total_goals,Target"]
    for tid in teams:
        lines.append(f"{tid},3,group")
    return "\n".join(lines)


def test_log_event_inserts_row():
    c = _conn()
    log_event(c, "start", chat_id=42)
    row = c.execute("SELECT event, chat_id FROM events").fetchone()
    assert row["event"] == "start"
    assert row["chat_id"] == 42


def test_log_event_no_chat_id():
    c = _conn()
    log_event(c, "leaderboard_snapshot")
    row = c.execute("SELECT chat_id FROM events").fetchone()
    assert row["chat_id"] is None


def test_log_event_never_raises(tmp_path):
    # Even with a broken conn it must not raise.
    import sqlite3
    bad = sqlite3.connect(":memory:")  # no schema
    log_event(bad, "start", chat_id=1)  # should silently swallow


def test_snapshot_leaderboard_empty_cohort():
    c = _conn()
    inserted = snapshot_leaderboard(c)
    assert inserted == 0


def test_snapshot_leaderboard_with_submissions():
    c = _conn()
    txt = _full_csv()
    ids = set(load_teams("data/teams.csv").keys())
    rows = parse_submission(txt, ids)
    h = hashlib.sha256(txt.encode()).hexdigest()
    set_display_name(c, 1, "Alice")
    store_submission(c, 1, rows, h)
    inserted = snapshot_leaderboard(c)
    assert inserted == 1
    row = c.execute("SELECT rank, combined FROM leaderboard_snapshots").fetchone()
    assert row["rank"] == 1
    assert isinstance(row["combined"], float)


def test_snapshot_leaderboard_idempotent():
    c = _conn()
    txt = _full_csv()
    ids = set(load_teams("data/teams.csv").keys())
    rows = parse_submission(txt, ids)
    h = hashlib.sha256(txt.encode()).hexdigest()
    set_display_name(c, 1, "Bob")
    store_submission(c, 1, rows, h)
    snapshot_leaderboard(c)
    second = snapshot_leaderboard(c)
    assert second == 0  # already snapshotted today
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/test_stats_integration.py -v
```
Expected: `ImportError` — `log_event` not found.

- [ ] **Step 3: Implement `log_event` and `snapshot_leaderboard` in `wc2026bot/db.py`**

Add these two functions at the end of `wc2026bot/db.py`:

```python
def log_event(conn: sqlite3.Connection, event: str,
              chat_id: int | None = None) -> None:
    try:
        conn.execute(
            "INSERT INTO events(event, chat_id) VALUES (?,?)", (event, chat_id))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass


def snapshot_leaderboard(conn: sqlite3.Connection) -> int:
    from datetime import date
    from wc2026bot.notify import cohort_scores, user_metrics
    today = date.today().isoformat()
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
```

- [ ] **Step 4: Run to confirm pass**

```
python -m pytest tests/test_stats_integration.py tests/test_db.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/db.py tests/test_stats_integration.py
git commit -m "feat: add log_event and snapshot_leaderboard helpers"
```

---

### Task 3: Instrument command handlers in `main.py`

**Files:**
- Modify: `wc2026bot/main.py`

**Interfaces:**
- Consumes: `log_event(conn, event, chat_id)` from `wc2026bot/db` (Task 2).
- No new interfaces produced — purely additive logging.

- [ ] **Step 1: Add `log_event` to import in `main.py`**

Change line 14:
```python
from wc2026bot.db import connect, init_db, seed_teams
```
to:
```python
from wc2026bot.db import connect, init_db, seed_teams, log_event
```

- [ ] **Step 2: Instrument each handler**

Apply the following changes to `build_app()` in `wc2026bot/main.py`. Each change adds exactly one `log_event` call. Show the full body of each function after the change:

**`start`:**
```python
async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    handlers.register_user(conn, update.effective_chat.id)
    log_event(conn, "start", update.effective_chat.id)
    await update.message.reply_text(handlers.cmd_start_text())
```

**`help_cmd`:**
```python
async def help_cmd(update: Update, _ctx):
    log_event(conn, "help", update.effective_chat.id)
    await update.message.reply_text(handlers.cmd_start_text())
```

**`setname`:**
```python
async def setname(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args:
        await update.message.reply_text("Usage: /setname <your name>")
        return
    try:
        name = handlers.set_display_name(
            conn, update.effective_chat.id, " ".join(ctx.args))
    except handlers.SetNameError as e:
        log_event(conn, "setname_fail", update.effective_chat.id)
        await update.message.reply_text(f"❌ {e}")
        return
    log_event(conn, "setname_ok", update.effective_chat.id)
    await update.message.reply_text(
        f"✅ Name set to '{name}'. Now /upload your predictions.")
```

**`me`:**
```python
async def me(update: Update, _ctx):
    gate = handlers.needs_name_msg(conn, update.effective_chat.id)
    if gate:
        await update.message.reply_text(gate)
        return
    log_event(conn, "cmd_me", update.effective_chat.id)
    await update.message.reply_text(
        handlers.me_text(conn, update.effective_chat.id))
```

**`rank`:**
```python
async def rank(update: Update, _ctx):
    log_event(conn, "cmd_rank", update.effective_chat.id)
    await update.message.reply_text(handlers.rank_text(conn))
```

**`today`:**
```python
async def today(update: Update, _ctx):
    log_event(conn, "cmd_today", update.effective_chat.id)
    d = datetime.now().astimezone().date().isoformat()
    await update.message.reply_text(
        handlers.matches_on_text(conn, d, team_names, "today"))
```

**`yesterday`:**
```python
async def yesterday(update: Update, _ctx):
    log_event(conn, "cmd_yesterday", update.effective_chat.id)
    d = (datetime.now().astimezone().date()
         - timedelta(days=1)).isoformat()
    await update.message.reply_text(
        handlers.matches_on_text(conn, d, team_names, "yesterday"))
```

**`scorers`:**
```python
async def scorers(update: Update, _ctx):
    log_event(conn, "cmd_scorers", update.effective_chat.id)
    data = await fd_client.fetch_scorers(limit=10)
    await update.message.reply_text(handlers.scorers_text(data))
```

**`standings`:**
```python
async def standings(update: Update, ctx):
    log_event(conn, "cmd_standings", update.effective_chat.id)
    data = await fd_client.fetch_standings()
    grp = ctx.args[0] if ctx.args else None
    await update.message.reply_text(handlers.standings_text(data, grp))
```

**`team`:**
```python
async def team(update: Update, ctx):
    gate = handlers.needs_name_msg(conn, update.effective_chat.id)
    if gate:
        await update.message.reply_text(gate)
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /team <ISO3>")
        return
    log_event(conn, "cmd_team", update.effective_chat.id)
    await update.message.reply_text(
        handlers.team_text(conn, update.effective_chat.id,
                           ctx.args[0], team_names))
```

**`upload_cmd`:**
```python
async def upload_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
    gate = handlers.needs_name_msg(conn, update.effective_chat.id)
    if gate:
        await update.message.reply_text(gate)
        return
    log_event(conn, "upload_prompt", update.effective_chat.id)
    await update.message.reply_text(
        "Send me your submission as a .csv file attachment "
        "(columns: ID, total_goals, Target).")
```

**`upload_doc`:**
```python
async def upload_doc(update: Update, _ctx):
    gate = handlers.needs_name_msg(conn, update.effective_chat.id)
    if gate:
        await update.message.reply_text(gate)
        return
    doc = update.message.document
    if doc is None:
        await update.message.reply_text("Reply with a .csv file.")
        return
    f = await doc.get_file()
    data = await f.download_as_bytearray()
    text = bytes(data).decode("utf-8", errors="replace")
    try:
        rows = parse_submission(text, valid_ids)
    except ValidationError as e:
        log_event(conn, "upload_fail", update.effective_chat.id)
        await update.message.reply_text(f"❌ {e}")
        return
    handlers.store_submission(
        conn, update.effective_chat.id, rows,
        hashlib.sha256(text.encode()).hexdigest())
    log_event(conn, "upload_ok", update.effective_chat.id)
    await update.message.reply_text(
        "✅ Submission stored. /me for your live standing.")
```

- [ ] **Step 3: Run the full test suite**

```
python -m pytest -q
```
Expected: all pass (no behaviour changes — only additive logging).

- [ ] **Step 4: Commit**

```bash
git add wc2026bot/main.py
git commit -m "feat: log all command events for stats tracking"
```

---

### Task 4: Instrument notification delivery in `main.py`

**Files:**
- Modify: `wc2026bot/main.py`

**Interfaces:**
- Consumes: `log_event` (already imported, Task 3).
- No new interfaces produced.

- [ ] **Step 1: Replace `_push` with instrumented version**

In `build_app()`, replace:

```python
async def _push(match_ids: list[str], kind: str):
    for mid in match_ids:
        for cid, text in notify.personalized_messages(
                conn, mid, team_names, kind=kind):
            try:
                await app.bot.send_message(cid, text)
            except Exception as e:  # noqa: BLE001
                log.warning("push to %s failed: %s", cid, e)
```

with:

```python
async def _push(match_ids: list[str], kind: str):
    for mid in match_ids:
        for cid, text in notify.personalized_messages(
                conn, mid, team_names, kind=kind):
            try:
                await app.bot.send_message(cid, text)
                log_event(conn, f"notify_{kind}_ok", cid)
            except Exception as e:  # noqa: BLE001
                log.warning("push to %s failed: %s", cid, e)
                log_event(conn, f"notify_{kind}_fail", cid)
```

- [ ] **Step 2: Run the full test suite**

```
python -m pytest -q
```
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add wc2026bot/main.py
git commit -m "feat: log notification delivery success and failure"
```

---

### Task 5: Daily leaderboard snapshot background task

**Files:**
- Modify: `wc2026bot/main.py`

**Interfaces:**
- Consumes: `snapshot_leaderboard(conn)` from `wc2026bot/db` (Task 2).
- Consumes: `log_event(conn, event)` from `wc2026bot/db` (Task 3).

- [ ] **Step 1: Add `snapshot_leaderboard` to the import**

Change:
```python
from wc2026bot.db import connect, init_db, seed_teams, log_event
```
to:
```python
from wc2026bot.db import connect, init_db, seed_teams, log_event, snapshot_leaderboard
```

- [ ] **Step 2: Add `run_daily_snapshot` coroutine**

Add this function directly above `build_app()` in `wc2026bot/main.py`:

```python
async def run_daily_snapshot(conn, stop_event: asyncio.Event) -> None:
    """Fire snapshot_leaderboard once per UTC day, ~00:05 UTC."""
    from datetime import timezone
    while not stop_event.is_set():
        now = datetime.now(timezone.utc)
        # Next 00:05 UTC
        tomorrow = (now + timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0)
        delay = (tomorrow - now).total_seconds()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            inserted = snapshot_leaderboard(conn)
            log_event(conn, "leaderboard_snapshot")
            log.info("leaderboard snapshot: %d rows", inserted)
        except Exception as e:  # noqa: BLE001
            log.warning("snapshot failed: %s", e)
```

- [ ] **Step 3: Launch the task in `_run()`**

In `_run()`, change:

```python
        poller_task = asyncio.create_task(
            run_poller(conn, clients, on_finished, stop, on_goal=on_goal))
```

to:

```python
        poller_task = asyncio.create_task(
            run_poller(conn, clients, on_finished, stop, on_goal=on_goal))
        snapshot_task = asyncio.create_task(
            run_daily_snapshot(conn, stop))
```

And in the `finally` block, after `await poller_task`, add:

```python
            await snapshot_task
```

- [ ] **Step 4: Run the full test suite**

```
python -m pytest -q
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/main.py
git commit -m "feat: add daily leaderboard snapshot background task"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Task |
|---|---|
| `events` table + indexes | Task 1 |
| `leaderboard_snapshots` table | Task 1 |
| `log_event` helper (never raises) | Task 2 |
| `snapshot_leaderboard` (idempotent) | Task 2 |
| All command handlers instrumented | Task 3 |
| Notification delivery logged | Task 4 |
| Daily snapshot background task | Task 5 |

**Placeholder scan:** No TBD, no "add appropriate X", all code blocks complete. ✓

**Type consistency:**
- `log_event(conn, event, chat_id=None)` — used identically across Tasks 2, 3, 4, 5. ✓
- `snapshot_leaderboard(conn)` — defined Task 2, imported Task 5. ✓
- `notify_{kind}_ok/fail` — `kind` is `"goal"` or `"finish"` from `_push`; matches event catalogue in spec. ✓
