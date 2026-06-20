# WC2026 Tracker — Addendum: Stage Engine Fix + Hardening

> Follows the final whole-branch review of the base plan. Addresses Critical
> findings C1 (ESPN never advances stage), C2 (champion never set), Important I1
> (shootout/winner), I2/I3 (DB durability + resource close), and deploy blockers
> D2/D3/M4. Decisions: Football-Data authoritative for rounds; finish-push stays
> generic (no goal-level push in v1).

## Root cause

Match rows are keyed by source-prefixed ids (`espn-…`, `fd-…`), so the same real
fixture becomes two rows — goals double-count once FD is enabled, and ESPN's
`match_stage` is a season slug (never a real stage) so no team advances past
`group`. Fix: **one stable match id per real fixture**, both sources merge into
it, and stage advancement keyed on the authoritative (FD) stage.

---

### Task 12: Unified match identity + stage engine + champion + winner

**Files:**
- Modify: `wc2026bot/state.py`, `wc2026bot/feeds/espn.py`, `wc2026bot/feeds/footballdata.py`, `wc2026bot/poller.py`
- Test: `tests/test_state.py` (add cases), `tests/test_stage_engine.py` (new)

**Interfaces:**
- `state.make_match_id(home_id: str, away_id: str, kickoff_time: str) -> str` — `f"{lo}__{hi}__{date10}"` where `lo,hi = sorted([home_id, away_id])`, `date10 = (kickoff_time or "")[:10]`. Stable regardless of which source/home-away orientation reports it.
- `MatchResult` gains `winner_team_id: str | None = None` (optional, default None — existing positional constructions unaffected).
- `apply_result` semantics change: stage-precedence upsert; on FINISHED (every time, idempotent) recompute goals + advance stage from the **stored** (authoritative) stage; `final` sets champion/runnerup via winner. Returns `newly_finished` (for notifications) unchanged.
- `poller.poll_once` now applies results from **all** clients (merge), not first-non-empty.

#### state.py — full new content

```python
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
```

#### espn.py — change two lines

- `match_id` uses `make_match_id`; `match_stage` is `"unknown"`; pass `winner_team_id` derived from score.

Replace the `out.append(...)` block and import:

```python
from wc2026bot.state import MatchResult, make_match_id
```

```python
            status = STATE_MAP.get(
                ev["status"]["type"]["state"], "SCHEDULED")
            kickoff = ev.get("date", "")
            winner = None
            if hs > as_:
                winner = home.zindi_id
            elif as_ > hs:
                winner = away.zindi_id
            out.append(MatchResult(
                match_id=make_match_id(home.zindi_id, away.zindi_id, kickoff),
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=hs, away_score=as_, status=status,
                match_stage="unknown",
                kickoff_time=kickoff,
                winner_team_id=winner))
```

#### footballdata.py — stable id, winner from score.winner, safer default

```python
from wc2026bot.state import MatchResult, make_match_id
```

```python
            ft = m.get("score", {}).get("fullTime", {})
            hs = ft.get("home") or 0
            as_ = ft.get("away") or 0
            kickoff = m.get("utcDate", "")
            winner_code = m.get("score", {}).get("winner")
            winner = None
            if winner_code == "HOME_TEAM":
                winner = home.zindi_id
            elif winner_code == "AWAY_TEAM":
                winner = away.zindi_id
            out.append(MatchResult(
                match_id=make_match_id(home.zindi_id, away.zindi_id, kickoff),
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=hs, away_score=as_,
                status=STATUS_MAP.get(m.get("status", ""), "SCHEDULED"),
                match_stage=_fd_stage(m.get("stage", "")),
                kickoff_time=kickoff,
                winner_team_id=winner))
```

`_fd_stage` default → `"unknown"`:

```python
def _fd_stage(stage: str) -> str:
    return {
        "GROUP_STAGE": "group", "LAST_32": "roundof32",
        "LAST_16": "roundof16", "QUARTER_FINALS": "qf",
        "SEMI_FINALS": "sf", "FINAL": "final",
    }.get(stage, "unknown")
```

#### poller.py — apply ALL clients (merge), ESPN-fresh-score order

`poll_once` must apply every client's results so FD's stage and ESPN's live
scores both land on the unified row. Apply in the order the clients are given;
`main.py` will order them `[FootballDataClient, EspnClient]` so ESPN's fresher
live score is applied last while stage-precedence protects the FD stage.

Replace `poll_once`:

```python
async def poll_once(conn, clients) -> list[str]:
    finished: list[str] = []
    for c in clients:
        try:
            results = await c.fetch()
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", type(c).__name__, e)
            continue
        for r in results:
            if apply_result(conn, r):
                finished.append(r.match_id)
    return finished
```

(Keep the `fetch_with_fallback` import removal: `poll_once` no longer uses it.
Leave `feeds/base.py` as-is.)

#### Tests

Add to `tests/test_state.py`:

```python
def test_make_match_id_stable_across_orientation():
    from wc2026bot.state import make_match_id
    a = make_match_id("WC-2026_AUT", "WC-2026_BEL", "2026-06-15T18:00Z")
    b = make_match_id("WC-2026_BEL", "WC-2026_AUT", "2026-06-15T20:00Z")
    # same teams + same date -> same id regardless of home/away or time-of-day
    assert a == b
```

New file `tests/test_stage_engine.py`:

```python
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.state import MatchResult, apply_result, make_match_id


def _conn():
    c = connect(":memory:")
    init_db(c)
    seed_teams(c, load_teams("data/teams.csv"))
    return c


def _stage(c, tid):
    return c.execute("SELECT current_stage FROM teams_state WHERE team_id=?",
                     (tid,)).fetchone()["current_stage"]


def test_unknown_stage_then_authoritative_advances():
    c = _conn()
    mid = make_match_id("WC-2026_FRA", "WC-2026_ARG", "2026-07-10T18:00Z")
    # ESPN-style first: finished but stage unknown -> goals only, no advance
    apply_result(c, MatchResult(mid, "WC-2026_FRA", "WC-2026_ARG", 2, 1,
                 "FINISHED", "unknown", "2026-07-10T18:00Z",
                 winner_team_id="WC-2026_FRA"))
    assert _stage(c, "WC-2026_FRA") == "group"  # not advanced yet
    # FD-style later: same match id, real stage qf -> both reach qf
    apply_result(c, MatchResult(mid, "WC-2026_FRA", "WC-2026_ARG", 2, 1,
                 "FINISHED", "qf", "2026-07-10T18:00Z",
                 winner_team_id="WC-2026_FRA"))
    assert _stage(c, "WC-2026_FRA") == "qf"
    assert _stage(c, "WC-2026_ARG") == "qf"
    # goals not double counted (one unified row)
    g = c.execute("SELECT actual_goals FROM teams_state WHERE team_id=?",
                  ("WC-2026_FRA",)).fetchone()["actual_goals"]
    assert g == 2


def test_final_sets_champion_and_runnerup():
    c = _conn()
    mid = make_match_id("WC-2026_FRA", "WC-2026_BRA", "2026-07-19T18:00Z")
    apply_result(c, MatchResult(mid, "WC-2026_FRA", "WC-2026_BRA", 0, 0,
                 "FINISHED", "final", "2026-07-19T18:00Z",
                 winner_team_id="WC-2026_BRA"))  # decided on penalties
    assert _stage(c, "WC-2026_BRA") == "champion"
    assert _stage(c, "WC-2026_FRA") == "runnerup"


def test_final_winner_from_score_when_no_winner_field():
    c = _conn()
    mid = make_match_id("WC-2026_ESP", "WC-2026_DEU", "2026-07-19T18:00Z")
    apply_result(c, MatchResult(mid, "WC-2026_ESP", "WC-2026_DEU", 3, 1,
                 "FINISHED", "final", "2026-07-19T18:00Z"))
    assert _stage(c, "WC-2026_ESP") == "champion"
    assert _stage(c, "WC-2026_DEU") == "runnerup"


def test_champion_not_downgraded_by_later_unknown_winner():
    c = _conn()
    mid = make_match_id("WC-2026_ESP", "WC-2026_DEU", "2026-07-19T18:00Z")
    # authoritative: ESP champion
    apply_result(c, MatchResult(mid, "WC-2026_ESP", "WC-2026_DEU", 1, 0,
                 "FINISHED", "final", "2026-07-19T18:00Z",
                 winner_team_id="WC-2026_ESP"))
    # a later poll with drawn score / no winner must not undo champion
    apply_result(c, MatchResult(mid, "WC-2026_ESP", "WC-2026_DEU", 1, 1,
                 "FINISHED", "final", "2026-07-19T18:00Z"))
    assert _stage(c, "WC-2026_ESP") == "champion"
    assert _stage(c, "WC-2026_DEU") == "runnerup"
```

**Steps:** write tests → run (fail) → apply the code changes above → run
`python -m pytest tests/test_state.py tests/test_stage_engine.py tests/test_poller.py tests/test_feeds.py -v`
(all pass) → run full suite `python -m pytest -q` → commit
`feat: unified match identity, authoritative stage, champion logic`.

---

### Task 13: Reliability hardening for always-on hosting

**Files:**
- Modify: `wc2026bot/db.py`, `wc2026bot/main.py`, `wc2026bot/poller.py`
- Test: `tests/test_db.py` (add WAL/pragma assertion is optional — see step)

#### db.py — WAL + busy timeout in `connect`

```python
def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
```

(`:memory:` silently ignores WAL — tests unaffected.)

#### poller.py — guard kickoff parse in `run_poller`

Replace the next-kickoff block inside `run_poller`'s try with:

```python
            nk = conn.execute(
                "SELECT MIN(kickoff_time) k FROM matches WHERE status='SCHEDULED'"
            ).fetchone()["k"]
            next_kickoff = None
            if nk:
                try:
                    next_kickoff = datetime.fromisoformat(
                        nk.replace("Z", "+00:00"))
                except ValueError:
                    next_kickoff = None
```

#### main.py — repo-root data path, resource close, SIGTERM

- Resolve teams path relative to the package, not CWD:

```python
from pathlib import Path
...
    teams_path = Path(__file__).resolve().parent.parent / "data" / "teams.csv"
    teams = load_teams(str(teams_path))
```

- `_run`: drive shutdown from `stop`, install signal handlers (guard Windows /
  unsupported loops), and close `http` + `conn`:

```python
import signal
...
async def _run():
    app, conn, clients, on_finished = build_app()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError):
            pass  # not supported on this platform (e.g. Windows)
    async with app:
        await app.start()
        await app.updater.start_polling()
        poller_task = asyncio.create_task(
            run_poller(conn, clients, on_finished, stop))
        try:
            await stop.wait()
        finally:
            stop.set()
            await poller_task
            await http.aclose()
            await app.updater.stop()
            await app.stop()
```

`http` must be in scope of `_run`. Since `build_app` constructs it, return it
too: change `build_app` to also return `http`, and update the unpacking:

```python
    return app, conn, clients, on_finished, http
```
```python
    app, conn, clients, on_finished, http = build_app()
```
Add `conn.close()` after `await app.stop()` in the `finally`.

Also annotate `build_app`'s return:

```python
def build_app() -> tuple:
```

**Steps:** apply changes → `python -c "import wc2026bot.main"` (exit 0) →
full suite `python -m pytest -q` (all pass) → commit
`fix: WAL durability, clean shutdown, repo-root data path`.

---

## Out of scope (documented v1 limitations)

- Goal-level push notifications (only match-finish push).
- Personalized finish payload deltas (ΔRMSE/ΔF1) — push is generic.
- `teams.csv` live feed-name verification — **pre-deploy manual step** (run
  against live ESPN + FD, confirm all 48 names resolve, esp. CPV/CUW/JOR/UZB,
  Türkiye, Côte d'Ivoire, Korea Republic).
- OUTLIER_GOALS > 35 warning (constant exists, unused).
