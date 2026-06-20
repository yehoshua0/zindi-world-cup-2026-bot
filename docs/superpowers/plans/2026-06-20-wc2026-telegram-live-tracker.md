# WC2026 Telegram Live Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public, multi-user Telegram bot that tracks Zindi WC2026 submissions live against real match results, reporting trailing RMSE / Macro-F1, leaderboard rank, and pushing goal/finish alerts.

**Architecture:** One always-on async Python process. A polling state machine fetches live results (ESPN primary, Football-Data verify), updates SQLite tournament state, recomputes per-user current-state metrics, and pushes deltas. `python-telegram-bot` v21 handles commands via long-polling.

**Tech Stack:** Python 3.11+, `python-telegram-bot` v21, `httpx`, `pytest`, SQLite (stdlib `sqlite3`).

## Global Constraints

- Submission format: `ID, total_goals, Target`; exactly 48 rows.
- Team IDs: `WC-2026_<ISO3>`; must match `data/Test.csv` exactly.
- Valid stage labels (7): `group`, `roundof32`, `roundof16`, `qf`, `sf`, `runnerup`, `champion`.
- Stage ordinal (worst→best): `group=1, roundof32=2, roundof16=3, qf=4, sf=5, runnerup=6, champion=7`.
- Metric: `Overall = 0.60 × RMSE_norm + 0.40 × MacroF1`, where `RMSE_norm = 1 − (rmse − min)/(max − min)` across the active cohort (if `max==min`, `RMSE_norm = 1.0`).
- RMSE and F1 are **current-state**: actual_goals = goals so far (shootout goals excluded); actual stage = furthest round reached so far / final exit stage.
- No external data ban concerns for the bot — it reads live results, it is not a submission.
- Python: type hints on all public functions. Tests with `pytest`. Frequent commits.
- All timestamps stored UTC ISO-8601.

---

## File Structure

```
wc2026bot/
  __init__.py
  config.py            # env config (BOT_TOKEN, DB_PATH, FOOTBALLDATA_KEY)
  db.py                # SQLite schema + connection helpers
  teams.py             # load teams.csv mapping (id<->country<->feed names)
  validation.py        # CSV upload parsing + validation
  evaluation.py        # RMSE, MacroF1, normalization, combined score, ranking
  state.py             # apply match results -> teams_state (goals, current_stage)
  feeds/
    __init__.py
    base.py            # MatchEvent dataclass + FeedClient protocol + fallback
    espn.py            # ESPN scoreboard client
    footballdata.py    # Football-Data.org client
  poller.py            # polling state machine
  notify.py            # build per-user payloads + dispatch
  handlers.py          # telegram command handlers
  main.py              # wire everything, run long-polling + poller task
data/
  Test.csv             # official competition file (copied from Downloads)
  teams.csv            # generated: zindi_id,country,iso3,espn_name,fd_name
scripts/
  build_teams_csv.py   # one-off generator for data/teams.csv
tests/
  test_teams.py
  test_validation.py
  test_evaluation.py
  test_state.py
  test_feeds.py
  test_poller.py
  test_notify.py
  fixtures/            # sample feed JSON
requirements.txt
README.md
.gitignore
```

---

### Task 1: Project scaffold, config, dependencies

**Files:**
- Create: `requirements.txt`, `.gitignore`, `wc2026bot/__init__.py`, `wc2026bot/config.py`
- Create: `data/Test.csv` (copy from `C:/Users/PC/Downloads/Test.csv`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.Settings` dataclass with `bot_token: str`, `db_path: str`, `footballdata_key: str | None`; `config.load_settings() -> Settings`.

- [ ] **Step 1: Write requirements.txt**

```
python-telegram-bot==21.6
httpx==0.27.2
pytest==8.3.3
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Write .gitignore**

```
.venv/
__pycache__/
*.pyc
wc2026.db
.env
```

- [ ] **Step 3: Copy Test.csv into the repo**

```bash
mkdir -p data && cp "C:/Users/PC/Downloads/Test.csv" data/Test.csv
wc -l data/Test.csv   # expect 49 (header + 48)
```

- [ ] **Step 4: Write the failing test** in `tests/test_config.py`

```python
import os
from wc2026bot.config import load_settings

def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("DB_PATH", "/tmp/x.db")
    s = load_settings()
    assert s.bot_token == "abc"
    assert s.db_path == "/tmp/x.db"
    assert s.footballdata_key is None

def test_load_settings_requires_token(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    import pytest
    with pytest.raises(ValueError):
        load_settings()
```

- [ ] **Step 5: Run test, verify fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (module `wc2026bot.config` not found).

- [ ] **Step 6: Implement** `wc2026bot/__init__.py` (empty) and `wc2026bot/config.py`

```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: str
    footballdata_key: str | None


def load_settings() -> Settings:
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise ValueError("BOT_TOKEN environment variable is required")
    return Settings(
        bot_token=token,
        db_path=os.environ.get("DB_PATH", "wc2026.db"),
        footballdata_key=os.environ.get("FOOTBALLDATA_KEY") or None,
    )
```

- [ ] **Step 7: Run test, verify pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed).

- [ ] **Step 8: Commit**

```bash
git add requirements.txt .gitignore wc2026bot/ data/Test.csv tests/test_config.py
git commit -m "feat: project scaffold and config loader"
```

---

### Task 2: Team mapping (teams.csv + loader)

**Files:**
- Create: `scripts/build_teams_csv.py`, `data/teams.csv` (generated), `wc2026bot/teams.py`
- Test: `tests/test_teams.py`

**Interfaces:**
- Produces: `teams.Team` dataclass (`zindi_id, country, iso3, espn_name, fd_name`); `teams.load_teams(path: str) -> dict[str, Team]` keyed by `zindi_id`; `teams.by_espn_name(teams) -> dict[str, Team]`; `teams.by_fd_name(teams) -> dict[str, Team]`.

- [ ] **Step 1: Write the generator** `scripts/build_teams_csv.py`

```python
"""Generate data/teams.csv from data/Test.csv.

Feed-name overrides cover countries whose ESPN / Football-Data display name
differs from the Zindi `country` value. VERIFY each row against the live feeds
before trusting (see Task 7 verification step).
"""
import csv

# country -> (espn_name, fd_name); default is country itself.
OVERRIDES = {
    "Czechia": ("Czech Republic", "Czech Republic"),
    "Turkiye": ("Turkey", "Türkiye"),
    "Cote d'Ivoire": ("Ivory Coast", "Côte d'Ivoire"),
    "DR Congo": ("Congo DR", "DR Congo"),
    "South Korea": ("South Korea", "Korea Republic"),
    "Cabo Verde": ("Cape Verde", "Cabo Verde"),
    "Curacao": ("Curaçao", "Curaçao"),
    "United States": ("United States", "United States"),
}


def main() -> None:
    rows = []
    with open("data/Test.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            zid = r["ID"].strip()
            country = r["country"].strip()
            iso3 = zid.split("_")[-1]
            espn, fd = OVERRIDES.get(country, (country, country))
            rows.append((zid, country, iso3, espn, fd))
    with open("data/teams.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["zindi_id", "country", "iso3", "espn_name", "fd_name"])
        w.writerows(rows)
    print(f"wrote {len(rows)} teams")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Generate the file**

Run: `python scripts/build_teams_csv.py`
Expected: `wrote 48 teams`, file `data/teams.csv` exists with 49 lines.

- [ ] **Step 3: Write the failing test** `tests/test_teams.py`

```python
from wc2026bot.teams import load_teams, by_espn_name, by_fd_name

def test_load_teams_has_48():
    teams = load_teams("data/teams.csv")
    assert len(teams) == 48
    assert teams["WC-2026_AUT"].country == "Austria"
    assert teams["WC-2026_AUT"].iso3 == "AUT"

def test_reverse_indexes_unique():
    teams = load_teams("data/teams.csv")
    assert len(by_espn_name(teams)) == 48
    assert len(by_fd_name(teams)) == 48
```

- [ ] **Step 4: Run test, verify fail**

Run: `pytest tests/test_teams.py -v`
Expected: FAIL (module not found).

- [ ] **Step 5: Implement** `wc2026bot/teams.py`

```python
import csv
from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    zindi_id: str
    country: str
    iso3: str
    espn_name: str
    fd_name: str


def load_teams(path: str) -> dict[str, Team]:
    out: dict[str, Team] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = Team(r["zindi_id"], r["country"], r["iso3"],
                     r["espn_name"], r["fd_name"])
            out[t.zindi_id] = t
    return out


def by_espn_name(teams: dict[str, Team]) -> dict[str, Team]:
    return {t.espn_name: t for t in teams.values()}


def by_fd_name(teams: dict[str, Team]) -> dict[str, Team]:
    return {t.fd_name: t for t in teams.values()}
```

- [ ] **Step 6: Run test, verify pass**

Run: `pytest tests/test_teams.py -v`
Expected: PASS (2 passed). If reverse-index counts < 48, two countries collided — fix `OVERRIDES`.

- [ ] **Step 7: Commit**

```bash
git add scripts/build_teams_csv.py data/teams.csv wc2026bot/teams.py tests/test_teams.py
git commit -m "feat: team id<->feed-name mapping"
```

---

### Task 3: Database schema and helpers

**Files:**
- Create: `wc2026bot/db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Produces: `db.connect(path: str) -> sqlite3.Connection` (row_factory = Row, foreign_keys ON); `db.init_db(conn)`; `db.seed_teams(conn, teams: dict[str, Team])`.

- [ ] **Step 1: Write the failing test** `tests/test_db.py`

```python
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams

def test_init_and_seed(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_db(conn)
    seed_teams(conn, load_teams("data/teams.csv"))
    n = conn.execute("SELECT COUNT(*) c FROM teams_state").fetchone()["c"]
    assert n == 48
    row = conn.execute(
        "SELECT current_stage, actual_goals FROM teams_state WHERE team_id=?",
        ("WC-2026_AUT",)).fetchone()
    assert row["current_stage"] == "group"
    assert row["actual_goals"] == 0
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_db.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/db.py`

```python
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_db.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/db.py tests/test_db.py
git commit -m "feat: sqlite schema and seed helpers"
```

---

### Task 4: Upload validation

**Files:**
- Create: `wc2026bot/validation.py`
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: `teams.load_teams`.
- Produces: `validation.ParsedRow` (`team_id: str, total_goals: float, target: str`); `validation.ValidationError(Exception)`; `validation.parse_submission(csv_text: str, valid_ids: set[str]) -> list[ParsedRow]` (raises `ValidationError` with a human message on any failure; returns 48 rows on success).
- Constant: `validation.VALID_STAGES: set[str]`.

- [ ] **Step 1: Write the failing test** `tests/test_validation.py`

```python
import pytest
from wc2026bot.validation import parse_submission, ValidationError

IDS = {f"WC-2026_{c}" for c in ("AUT", "BEL")}

def _csv(rows):
    return "ID,total_goals,Target\n" + "\n".join(rows)

def test_valid_two_team_subset():
    txt = _csv(["WC-2026_AUT,3,group", "WC-2026_BEL,7.5,sf"])
    out = parse_submission(txt, IDS)
    assert len(out) == 2
    assert out[0].team_id == "WC-2026_AUT"
    assert out[1].total_goals == 7.5
    assert out[1].target == "sf"

def test_bad_stage_rejected():
    txt = _csv(["WC-2026_AUT,3,group", "WC-2026_BEL,3,final"])
    with pytest.raises(ValidationError, match="stage"):
        parse_submission(txt, IDS)

def test_negative_goals_rejected():
    txt = _csv(["WC-2026_AUT,-1,group", "WC-2026_BEL,3,group"])
    with pytest.raises(ValidationError, match="negative"):
        parse_submission(txt, IDS)

def test_unknown_id_rejected():
    txt = _csv(["WC-2026_XXX,3,group", "WC-2026_BEL,3,group"])
    with pytest.raises(ValidationError, match="unknown"):
        parse_submission(txt, IDS)

def test_duplicate_id_rejected():
    txt = _csv(["WC-2026_AUT,3,group", "WC-2026_AUT,3,group"])
    with pytest.raises(ValidationError, match="duplicate"):
        parse_submission(txt, IDS)

def test_missing_team_rejected():
    txt = _csv(["WC-2026_AUT,3,group"])
    with pytest.raises(ValidationError, match="missing"):
        parse_submission(txt, IDS)
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_validation.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/validation.py`

```python
import csv
import io
from dataclasses import dataclass

VALID_STAGES: set[str] = {
    "group", "roundof32", "roundof16", "qf", "sf", "runnerup", "champion",
}
OUTLIER_GOALS = 35.0


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class ParsedRow:
    team_id: str
    total_goals: float
    target: str


def parse_submission(csv_text: str, valid_ids: set[str]) -> list[ParsedRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"ID", "total_goals", "Target"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValidationError(
            "CSV must have columns: ID, total_goals, Target")
    rows: list[ParsedRow] = []
    seen: set[str] = set()
    for i, r in enumerate(reader, start=2):
        tid = (r["ID"] or "").strip()
        if tid not in valid_ids:
            raise ValidationError(f"row {i}: unknown team id '{tid}'")
        if tid in seen:
            raise ValidationError(f"row {i}: duplicate team id '{tid}'")
        seen.add(tid)
        raw = (r["total_goals"] or "").strip()
        try:
            goals = float(raw)
        except ValueError:
            raise ValidationError(f"row {i}: total_goals '{raw}' is not a number")
        if goals < 0:
            raise ValidationError(f"row {i}: total_goals is negative")
        target = (r["Target"] or "").strip()
        if target not in VALID_STAGES:
            raise ValidationError(
                f"row {i}: invalid stage '{target}' (allowed: "
                + ", ".join(sorted(VALID_STAGES)) + ")")
        rows.append(ParsedRow(tid, goals, target))
    missing = valid_ids - seen
    if missing:
        raise ValidationError(
            f"missing {len(missing)} team(s): {', '.join(sorted(missing))}")
    return rows
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_validation.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/validation.py tests/test_validation.py
git commit -m "feat: submission csv validation"
```

---

### Task 5: Evaluation engine

**Files:**
- Create: `wc2026bot/evaluation.py`
- Test: `tests/test_evaluation.py`

**Interfaces:**
- Produces:
  - `evaluation.rmse(pred: dict[str, float], actual: dict[str, float]) -> float` (keys = team_id; both must cover the same teams).
  - `evaluation.macro_f1(pred: dict[str, str], actual: dict[str, str]) -> float` (macro over the 7 `VALID_STAGES`).
  - `evaluation.normalize_rmse(raw: float, lo: float, hi: float) -> float`.
  - `evaluation.combined(rmse_norm: float, f1: float) -> float` → `0.6*rmse_norm + 0.4*f1`.
  - `evaluation.UserScore` dataclass (`user_id: int, raw_rmse: float, f1: float, rmse_norm: float, combined: float, rank: int`).
  - `evaluation.rank_cohort(per_user: dict[int, tuple[float, float]]) -> list[UserScore]` where the tuple is `(raw_rmse, f1)`; returns list sorted by `combined` desc with `rank` filled (1-based).

- [ ] **Step 1: Write the failing test** `tests/test_evaluation.py`

```python
import math
from wc2026bot.evaluation import (
    rmse, macro_f1, normalize_rmse, combined, rank_cohort,
)

def test_rmse_known():
    pred = {"a": 3.0, "b": 1.0}
    actual = {"a": 1.0, "b": 1.0}
    # errors 2,0 -> mean sq = 2 -> sqrt(2)
    assert math.isclose(rmse(pred, actual), math.sqrt(2))

def test_macro_f1_perfect():
    pred = {"a": "group", "b": "champion"}
    actual = {"a": "group", "b": "champion"}
    # only classes present score 1; absent classes contribute 0 over 7
    assert math.isclose(macro_f1(pred, actual), 2 / 7)

def test_macro_f1_all_wrong_one_class():
    pred = {"a": "group", "b": "group"}
    actual = {"a": "qf", "b": "sf"}
    assert macro_f1(pred, actual) == 0.0

def test_normalize_rmse_edges():
    assert normalize_rmse(5, 5, 5) == 1.0           # degenerate
    assert normalize_rmse(2, 2, 4) == 1.0           # best (min)
    assert normalize_rmse(4, 2, 4) == 0.0           # worst (max)
    assert normalize_rmse(3, 2, 4) == 0.5

def test_combined():
    assert math.isclose(combined(1.0, 0.5), 0.8)

def test_rank_cohort_orders_by_combined():
    # user1 best rmse worst f1; user2 worst rmse best f1
    res = rank_cohort({1: (2.0, 0.2), 2: (4.0, 0.9)})
    by_id = {u.user_id: u for u in res}
    # user1 rmse_norm=1.0 -> 0.6 + 0.08 = 0.68
    # user2 rmse_norm=0.0 -> 0.0 + 0.36 = 0.36
    assert by_id[1].rank == 1
    assert by_id[2].rank == 2
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_evaluation.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/evaluation.py`

```python
import math
from dataclasses import dataclass

from wc2026bot.validation import VALID_STAGES


def rmse(pred: dict[str, float], actual: dict[str, float]) -> float:
    keys = list(actual.keys())
    if not keys:
        return 0.0
    se = sum((pred[k] - actual[k]) ** 2 for k in keys)
    return math.sqrt(se / len(keys))


def macro_f1(pred: dict[str, str], actual: dict[str, str]) -> float:
    keys = list(actual.keys())
    total = 0.0
    for stage in VALID_STAGES:
        tp = sum(1 for k in keys if pred[k] == stage and actual[k] == stage)
        fp = sum(1 for k in keys if pred[k] == stage and actual[k] != stage)
        fn = sum(1 for k in keys if pred[k] != stage and actual[k] == stage)
        denom = 2 * tp + fp + fn
        f1 = (2 * tp / denom) if denom else 0.0
        total += f1
    return total / len(VALID_STAGES)


def normalize_rmse(raw: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 1.0
    return 1.0 - (raw - lo) / (hi - lo)


def combined(rmse_norm: float, f1: float) -> float:
    return 0.6 * rmse_norm + 0.4 * f1


@dataclass(frozen=True)
class UserScore:
    user_id: int
    raw_rmse: float
    f1: float
    rmse_norm: float
    combined: float
    rank: int


def rank_cohort(per_user: dict[int, tuple[float, float]]) -> list[UserScore]:
    if not per_user:
        return []
    rmses = [r for r, _ in per_user.values()]
    lo, hi = min(rmses), max(rmses)
    rows = []
    for uid, (raw, f1) in per_user.items():
        rn = normalize_rmse(raw, lo, hi)
        rows.append((uid, raw, f1, rn, combined(rn, f1)))
    rows.sort(key=lambda x: x[4], reverse=True)
    return [
        UserScore(uid, raw, f1, rn, comb, i)
        for i, (uid, raw, f1, rn, comb) in enumerate(rows, start=1)
    ]
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_evaluation.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/evaluation.py tests/test_evaluation.py
git commit -m "feat: current-state evaluation engine"
```

---

### Task 6: Tournament state updates

**Files:**
- Create: `wc2026bot/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `feeds.base.MatchResult` (defined here ahead of Task 7 to avoid a cycle — see note). To keep Task 6 independent, define the input as a plain dataclass **in this module**: `state.MatchResult` (`match_id, home_team_id, away_team_id, home_score, away_score, status, match_stage, kickoff_time`). Task 7's feed clients will produce this same dataclass.
- Produces:
  - `state.STAGE_ORDINAL: dict[str, int]` and `state.ORDINAL_STAGE: dict[int, str]`.
  - `state.apply_result(conn, r: MatchResult) -> bool` — upserts the match row; on transition to `FINISHED`, recomputes `actual_goals` for both teams from all finished matches and bumps `current_stage`. Returns `True` if the match status changed to `FINISHED` this call (used to trigger notifications).
  - `state.recompute_team_goals(conn, team_id) -> int`.
  - `state.advance_stage(conn, team_id, new_stage) -> None` (only ever moves a team forward in ordinal, never back).

- [ ] **Step 1: Write the failing test** `tests/test_state.py`

```python
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.state import MatchResult, apply_result

def _conn():
    c = connect(":memory:")
    init_db(c)
    seed_teams(c, load_teams("data/teams.csv"))
    return c

def test_finished_match_updates_goals_and_returns_true():
    c = _conn()
    r = MatchResult("m1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                    "FINISHED", "group", "2026-06-15T18:00:00Z")
    assert apply_result(c, r) is True
    aut = c.execute("SELECT actual_goals FROM teams_state WHERE team_id=?",
                    ("WC-2026_AUT",)).fetchone()["actual_goals"]
    assert aut == 2

def test_live_match_does_not_finalize():
    c = _conn()
    r = MatchResult("m1", "WC-2026_AUT", "WC-2026_BEL", 1, 0,
                    "LIVE", "group", "2026-06-15T18:00:00Z")
    assert apply_result(c, r) is False
    aut = c.execute("SELECT actual_goals FROM teams_state WHERE team_id=?",
                    ("WC-2026_AUT",)).fetchone()["actual_goals"]
    assert aut == 0  # goals only committed on FINISHED

def test_knockout_advances_stage_forward_only():
    c = _conn()
    apply_result(c, MatchResult("m1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                  "FINISHED", "roundof32", "2026-06-30T18:00:00Z"))
    aut = c.execute("SELECT current_stage FROM teams_state WHERE team_id=?",
                    ("WC-2026_AUT",)).fetchone()["current_stage"]
    # playing a roundof32 match means team reached at least roundof32
    assert aut == "roundof32"

def test_goals_accumulate_over_two_matches():
    c = _conn()
    apply_result(c, MatchResult("m1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                  "FINISHED", "group", "2026-06-15T18:00:00Z"))
    apply_result(c, MatchResult("m2", "WC-2026_AUT", "WC-2026_HRV", 3, 0,
                  "FINISHED", "group", "2026-06-19T18:00:00Z"))
    aut = c.execute("SELECT actual_goals FROM teams_state WHERE team_id=?",
                    ("WC-2026_AUT",)).fetchone()["actual_goals"]
    assert aut == 5
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_state.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/state.py`

```python
import sqlite3
from dataclasses import dataclass

STAGE_ORDINAL: dict[str, int] = {
    "group": 1, "roundof32": 2, "roundof16": 3, "qf": 4,
    "sf": 5, "runnerup": 6, "champion": 7,
}
ORDINAL_STAGE: dict[int, str] = {v: k for k, v in STAGE_ORDINAL.items()}

# A knockout match at stage X means both teams *reached* stage X.
MATCH_STAGE_TO_REACHED = {
    "group": "group",
    "roundof32": "roundof32",
    "roundof16": "roundof16",
    "qf": "qf",
    "sf": "sf",
    "final": "runnerup",  # reaching the final = at least runnerup
}


@dataclass(frozen=True)
class MatchResult:
    match_id: str
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    status: str  # SCHEDULED | LIVE | FINISHED
    match_stage: str
    kickoff_time: str


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
    if STAGE_ORDINAL[new_stage] > STAGE_ORDINAL[cur["current_stage"]]:
        conn.execute("UPDATE teams_state SET current_stage=? WHERE team_id=?",
                     (new_stage, team_id))


def apply_result(conn: sqlite3.Connection, r: MatchResult) -> bool:
    prev = conn.execute("SELECT status FROM matches WHERE match_id=?",
                        (r.match_id,)).fetchone()
    prev_status = prev["status"] if prev else None
    conn.execute(
        """
        INSERT INTO matches(match_id, home_team_id, away_team_id, home_score,
                            away_score, status, match_stage, kickoff_time)
        VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(match_id) DO UPDATE SET
            home_score=excluded.home_score,
            away_score=excluded.away_score,
            status=excluded.status
        """,
        (r.match_id, r.home_team_id, r.away_team_id, r.home_score,
         r.away_score, r.status, r.match_stage, r.kickoff_time),
    )
    newly_finished = r.status == "FINISHED" and prev_status != "FINISHED"
    if newly_finished:
        for tid in (r.home_team_id, r.away_team_id):
            recompute_team_goals(conn, tid)
        reached = MATCH_STAGE_TO_REACHED.get(r.match_stage, r.match_stage)
        advance_stage(conn, r.home_team_id, reached)
        advance_stage(conn, r.away_team_id, reached)
    conn.commit()
    return newly_finished
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_state.py -v`
Expected: PASS (4 passed).

> **Note on exit stages / runner-up / champion:** v1 derives `current_stage`
> from the stage of matches a team played (furthest reached). Distinguishing
> the final's winner (`champion`) from loser (`runnerup`), and marking
> eliminated teams' *final* exit stage vs still-active, is refined in Task 8
> using match win/loss + a team's last finished match. The ordinal-forward rule
> here is the safe baseline.

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/state.py tests/test_state.py
git commit -m "feat: tournament state updates from match results"
```

---

### Task 7: Feed clients with fallback

**Files:**
- Create: `wc2026bot/feeds/__init__.py`, `wc2026bot/feeds/base.py`, `wc2026bot/feeds/espn.py`, `wc2026bot/feeds/footballdata.py`
- Create: `tests/fixtures/espn_scoreboard.json`, `tests/fixtures/footballdata_matches.json`
- Test: `tests/test_feeds.py`

**Interfaces:**
- Consumes: `state.MatchResult`, `teams.by_espn_name`, `teams.by_fd_name`.
- Produces:
  - `feeds.base.FeedClient` protocol: `async fetch(self) -> list[MatchResult]`.
  - `feeds.base.fetch_with_fallback(clients: list[FeedClient]) -> list[MatchResult]` — tries clients in order, returns first non-empty result; on all-fail returns `[]` and logs.
  - `feeds.espn.EspnClient(teams_by_espn: dict[str, Team], http: httpx.AsyncClient)`.
  - `feeds.footballdata.FootballDataClient(teams_by_fd, http, api_key)`.
  - Each client maps unknown team names to `None` and **skips** those matches (logged), never crashes.

- [ ] **Step 1: Capture real fixture JSON** (one-off, requires network)

```bash
curl -s "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard" \
  -o tests/fixtures/espn_scoreboard.json
```
If offline, hand-write a minimal fixture with the same shape: top-level
`events[]`, each with `competitions[0].competitors[]` (each has
`homeAway`, `score`, `team.displayName`), `status.type.state`
(`pre`|`in`|`post`), and `id`.

- [ ] **Step 2: Write the failing test** `tests/test_feeds.py`

```python
import json, asyncio
import pytest
from wc2026bot.teams import load_teams, by_espn_name
from wc2026bot.feeds.espn import EspnClient
from wc2026bot.feeds.base import fetch_with_fallback

class FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p

class FakeHttp:
    def __init__(self, payload): self._p = payload
    async def get(self, url, **kw): return FakeResp(self._p)

ESPN_SAMPLE = {
  "events": [{
    "id": "401",
    "status": {"type": {"state": "post"}},
    "competitions": [{"competitors": [
      {"homeAway": "home", "score": "2", "team": {"displayName": "Austria"}},
      {"homeAway": "away", "score": "1", "team": {"displayName": "Belgium"}},
    ]}]
  }]
}

def test_espn_maps_finished_match():
    teams = load_teams("data/teams.csv")
    client = EspnClient(by_espn_name(teams), FakeHttp(ESPN_SAMPLE))
    res = asyncio.run(client.fetch())
    assert len(res) == 1
    m = res[0]
    assert m.home_team_id == "WC-2026_AUT"
    assert m.away_team_id == "WC-2026_BEL"
    assert (m.home_score, m.away_score) == (2, 1)
    assert m.status == "FINISHED"

def test_espn_skips_unknown_team():
    teams = load_teams("data/teams.csv")
    bad = {"events": [{"id": "9", "status": {"type": {"state": "post"}},
        "competitions": [{"competitors": [
          {"homeAway": "home", "score": "0", "team": {"displayName": "Narnia"}},
          {"homeAway": "away", "score": "0", "team": {"displayName": "Belgium"}},
        ]}]}]}
    client = EspnClient(by_espn_name(teams), FakeHttp(bad))
    assert asyncio.run(client.fetch()) == []

def test_fallback_uses_second_on_empty():
    class Empty:
        async def fetch(self): return []
    class Has:
        async def fetch(self):
            from wc2026bot.state import MatchResult
            return [MatchResult("m", "WC-2026_AUT", "WC-2026_BEL", 0, 0,
                    "SCHEDULED", "group", "2026-06-15T18:00:00Z")]
    res = asyncio.run(fetch_with_fallback([Empty(), Has()]))
    assert len(res) == 1
```

- [ ] **Step 3: Run test, verify fail**

Run: `pytest tests/test_feeds.py -v`
Expected: FAIL (modules not found).

- [ ] **Step 4: Implement** `wc2026bot/feeds/__init__.py` (empty), then `wc2026bot/feeds/base.py`

```python
import logging
from typing import Protocol

from wc2026bot.state import MatchResult

log = logging.getLogger(__name__)


class FeedClient(Protocol):
    async def fetch(self) -> list[MatchResult]: ...


async def fetch_with_fallback(clients: list[FeedClient]) -> list[MatchResult]:
    for c in clients:
        try:
            res = await c.fetch()
            if res:
                return res
        except Exception as e:  # noqa: BLE001
            log.warning("feed %s failed: %s", type(c).__name__, e)
    return []
```

- [ ] **Step 5: Implement** `wc2026bot/feeds/espn.py`

```python
import logging
from wc2026bot.state import MatchResult
from wc2026bot.teams import Team

log = logging.getLogger(__name__)
URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
       "fifa.world/scoreboard")
STATE_MAP = {"pre": "SCHEDULED", "in": "LIVE", "post": "FINISHED"}


class EspnClient:
    def __init__(self, teams_by_espn: dict[str, Team], http) -> None:
        self._teams = teams_by_espn
        self._http = http

    async def fetch(self) -> list[MatchResult]:
        resp = await self._http.get(URL)
        resp.raise_for_status()
        out: list[MatchResult] = []
        for ev in resp.json().get("events", []):
            comp = ev["competitions"][0]
            home = away = None
            for c in comp["competitors"]:
                t = self._teams.get(c["team"]["displayName"])
                if c["homeAway"] == "home":
                    home, hs = t, int(c["score"])
                else:
                    away, as_ = t, int(c["score"])
            if home is None or away is None:
                log.info("espn: skip unmapped match %s", ev.get("id"))
                continue
            status = STATE_MAP.get(
                ev["status"]["type"]["state"], "SCHEDULED")
            out.append(MatchResult(
                match_id=f"espn-{ev['id']}",
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=hs, away_score=as_, status=status,
                match_stage=ev.get("season", {}).get("slug", "group") or "group",
                kickoff_time=ev.get("date", "")))
        return out
```

> **Stage caveat:** ESPN does not cleanly label WC round per event. Default to
> `group`; the authoritative round comes from a static fixture calendar wired in
> Task 8. For now `match_stage` defaults to `group` so goal tracking works
> regardless.

- [ ] **Step 6: Implement** `wc2026bot/feeds/footballdata.py`

```python
import logging
from wc2026bot.state import MatchResult
from wc2026bot.teams import Team

log = logging.getLogger(__name__)
URL = "https://api.football-data.org/v4/competitions/WC/matches"
STATUS_MAP = {
    "SCHEDULED": "SCHEDULED", "TIMED": "SCHEDULED", "IN_PLAY": "LIVE",
    "PAUSED": "LIVE", "FINISHED": "FINISHED",
}


class FootballDataClient:
    def __init__(self, teams_by_fd: dict[str, Team], http,
                 api_key: str | None) -> None:
        self._teams = teams_by_fd
        self._http = http
        self._key = api_key

    async def fetch(self) -> list[MatchResult]:
        if not self._key:
            return []
        headers = {"X-Auth-Token": self._key}
        resp = await self._http.get(URL, headers=headers)
        resp.raise_for_status()
        out: list[MatchResult] = []
        for m in resp.json().get("matches", []):
            home = self._teams.get(m["homeTeam"].get("name", ""))
            away = self._teams.get(m["awayTeam"].get("name", ""))
            if home is None or away is None:
                log.info("fd: skip unmapped match %s", m.get("id"))
                continue
            ft = m.get("score", {}).get("fullTime", {})
            out.append(MatchResult(
                match_id=f"fd-{m['id']}",
                home_team_id=home.zindi_id, away_team_id=away.zindi_id,
                home_score=ft.get("home") or 0, away_score=ft.get("away") or 0,
                status=STATUS_MAP.get(m.get("status", ""), "SCHEDULED"),
                match_stage=_fd_stage(m.get("stage", "")),
                kickoff_time=m.get("utcDate", "")))
        return out


def _fd_stage(stage: str) -> str:
    return {
        "GROUP_STAGE": "group", "LAST_32": "roundof32",
        "LAST_16": "roundof16", "QUARTER_FINALS": "qf",
        "SEMI_FINALS": "sf", "FINAL": "final",
    }.get(stage, "group")
```

- [ ] **Step 7: Run test, verify pass**

Run: `pytest tests/test_feeds.py -v`
Expected: PASS (3 passed).

- [ ] **Step 8: Feed-name verification (manual, network)**

Run a throwaway script that fetches ESPN + Football-Data live and prints any
team display name not present in `by_espn_name` / `by_fd_name`. Update
`scripts/build_teams_csv.py` `OVERRIDES`, regenerate `data/teams.csv`, re-run
Task 2 tests. **Goal: zero unmapped names across all 48 teams.** Pay attention
to debutants CPV, CUW, JOR, UZB.

- [ ] **Step 9: Commit**

```bash
git add wc2026bot/feeds/ tests/test_feeds.py tests/fixtures/ data/teams.csv
git commit -m "feat: espn + football-data feed clients with fallback"
```

---

### Task 8: Polling state machine

**Files:**
- Create: `wc2026bot/poller.py`
- Test: `tests/test_poller.py`

**Interfaces:**
- Consumes: `feeds.base.fetch_with_fallback`, `state.apply_result`.
- Produces:
  - `poller.poll_interval(now, next_kickoff, any_live) -> int` (seconds): IN_PLAY→60, PRE_MATCH (within 30 min of kickoff)→300, DORMANT→21600.
  - `poller.poll_once(conn, clients) -> list[str]` — fetches, applies each result, returns the list of `match_id`s that newly finished this cycle.
  - `poller.run_poller(conn, clients, on_finished, stop_event)` — async loop; sleeps `poll_interval`; calls `on_finished(match_ids)` after each cycle that produces finishes. (Designed so tests can call `poll_once` directly without the loop.)

- [ ] **Step 1: Write the failing test** `tests/test_poller.py`

```python
import asyncio
from datetime import datetime, timedelta, timezone
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.state import MatchResult
from wc2026bot.poller import poll_interval, poll_once

def test_intervals():
    now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    assert poll_interval(now, None, any_live=True) == 60
    soon = now + timedelta(minutes=10)
    assert poll_interval(now, soon, any_live=False) == 300
    far = now + timedelta(hours=10)
    assert poll_interval(now, far, any_live=False) == 21600

def test_poll_once_returns_newly_finished():
    c = connect(":memory:"); init_db(c); seed_teams(c, load_teams("data/teams.csv"))
    class Client:
        def __init__(self, status): self.status = status
        async def fetch(self):
            return [MatchResult("espn-1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                    self.status, "group", "2026-06-15T18:00:00Z")]
    # first cycle: live -> no finishes
    assert asyncio.run(poll_once(c, [Client("LIVE")])) == []
    # second cycle: finished -> one finish
    assert asyncio.run(poll_once(c, [Client("FINISHED")])) == ["espn-1"]
    # third cycle: still finished -> idempotent, no new finish
    assert asyncio.run(poll_once(c, [Client("FINISHED")])) == []
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_poller.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/poller.py`

```python
import asyncio
import logging
from datetime import datetime, timedelta

from wc2026bot.feeds.base import fetch_with_fallback
from wc2026bot.state import apply_result

log = logging.getLogger(__name__)


def poll_interval(now: datetime, next_kickoff: datetime | None,
                  any_live: bool) -> int:
    if any_live:
        return 60
    if next_kickoff is not None and next_kickoff - now <= timedelta(minutes=30):
        return 300
    return 21600


async def poll_once(conn, clients) -> list[str]:
    results = await fetch_with_fallback(clients)
    finished: list[str] = []
    for r in results:
        if apply_result(conn, r):
            finished.append(r.match_id)
    return finished


async def run_poller(conn, clients, on_finished, stop_event) -> None:
    while not stop_event.is_set():
        try:
            finished = await poll_once(conn, clients)
            if finished:
                await on_finished(finished)
            any_live = conn.execute(
                "SELECT 1 FROM matches WHERE status='LIVE' LIMIT 1"
            ).fetchone() is not None
            nk = conn.execute(
                "SELECT MIN(kickoff_time) k FROM matches WHERE status='SCHEDULED'"
            ).fetchone()["k"]
            next_kickoff = (datetime.fromisoformat(nk.replace("Z", "+00:00"))
                            if nk else None)
            delay = poll_interval(datetime.now().astimezone(),
                                  next_kickoff, any_live)
        except Exception as e:  # noqa: BLE001
            log.exception("poll cycle error: %s", e)
            delay = 300
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_poller.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/poller.py tests/test_poller.py
git commit -m "feat: polling state machine"
```

---

### Task 9: Notification payload builder

**Files:**
- Create: `wc2026bot/notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: `db`, `evaluation`, `state`.
- Produces:
  - `notify.user_metrics(conn, submission_id) -> tuple[float, float]` — `(raw_rmse, macro_f1)` for one active submission against current `teams_state`.
  - `notify.cohort_scores(conn) -> list[UserScore]` — ranks all active submissions.
  - `notify.build_finish_message(conn, match_id, team_names) -> str` — human text for a finished match (score + which teams advanced/eliminated). Independent of any single user.
  - `notify.affected_users(conn, match_id) -> list[int]` — telegram_chat_ids of users whose active submission references either team in the match.

- [ ] **Step 1: Write the failing test** `tests/test_notify.py`

```python
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.state import MatchResult, apply_result
from wc2026bot.notify import user_metrics, cohort_scores, affected_users

def _setup():
    c = connect(":memory:"); init_db(c); seed_teams(c, load_teams("data/teams.csv"))
    c.execute("INSERT INTO users(telegram_chat_id) VALUES (111)")
    uid = c.execute("SELECT user_id FROM users").fetchone()["user_id"]
    c.execute("INSERT INTO submissions(user_id, file_hash) VALUES (?, 'h')", (uid,))
    sid = c.execute("SELECT submission_id FROM submissions").fetchone()["submission_id"]
    # full 48-row prediction: everyone group, 3 goals, except AUT champion 10
    teams = load_teams("data/teams.csv")
    for tid in teams:
        g, st = (10.0, "champion") if tid == "WC-2026_AUT" else (3.0, "group")
        c.execute("INSERT INTO predictions(submission_id, team_id, predicted_goals, predicted_stage) VALUES (?,?,?,?)",
                  (sid, tid, g, st))
    c.commit()
    return c, sid

def test_user_metrics_runs_over_48():
    c, sid = _setup()
    rmse, f1 = user_metrics(c, sid)
    assert rmse >= 0
    assert 0 <= f1 <= 1

def test_cohort_scores_ranks_one_user():
    c, sid = _setup()
    scores = cohort_scores(c)
    assert len(scores) == 1
    assert scores[0].rank == 1

def test_affected_users_after_match():
    c, sid = _setup()
    apply_result(c, MatchResult("espn-1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                 "FINISHED", "group", "2026-06-15T18:00:00Z"))
    assert 111 in affected_users(c, "espn-1")
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_notify.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/notify.py`

```python
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_notify.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/notify.py tests/test_notify.py
git commit -m "feat: notification metrics and payload builders"
```

---

### Task 10: Telegram command handlers

**Files:**
- Create: `wc2026bot/handlers.py`
- Test: `tests/test_handlers.py`

**Interfaces:**
- Consumes: `validation.parse_submission`, `notify.cohort_scores`, `notify.user_metrics`, `db`.
- Produces pure helper functions (testable without Telegram), each returning the reply string:
  - `handlers.cmd_start_text() -> str`
  - `handlers.register_user(conn, chat_id) -> int` (returns user_id, idempotent)
  - `handlers.store_submission(conn, chat_id, rows, file_hash) -> None` (deactivates prior, inserts new + predictions)
  - `handlers.me_text(conn, chat_id) -> str`
  - `handlers.rank_text(conn, top: int = 10) -> str`
  - `handlers.team_text(conn, chat_id, iso3, team_names) -> str`
- Telegram wiring (`CommandHandler`, `MessageHandler` for document upload) lives in `main.py` and is exercised manually, not unit-tested.

- [ ] **Step 1: Write the failing test** `tests/test_handlers.py`

```python
import hashlib
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.validation import parse_submission
from wc2026bot.handlers import register_user, store_submission, me_text, rank_text

def _full_csv():
    teams = load_teams("data/teams.csv")
    lines = ["ID,total_goals,Target"]
    for tid in teams:
        lines.append(f"{tid},3,group")
    return "\n".join(lines)

def _conn():
    c = connect(":memory:"); init_db(c); seed_teams(c, load_teams("data/teams.csv"))
    return c

def test_register_idempotent():
    c = _conn()
    a = register_user(c, 555)
    b = register_user(c, 555)
    assert a == b

def test_store_and_me():
    c = _conn()
    register_user(c, 555)
    txt = _full_csv()
    rows = parse_submission(txt, {r["team_id"] for r in [
        type("R", (), {"team_id": t}) for t in load_teams("data/teams.csv")]})
    rows = parse_submission(txt, set(load_teams("data/teams.csv").keys()))
    store_submission(c, 555, rows, hashlib.sha256(txt.encode()).hexdigest())
    out = me_text(c, 555)
    assert "RMSE" in out and "F1" in out

def test_new_upload_supersedes():
    c = _conn(); register_user(c, 555)
    ids = set(load_teams("data/teams.csv").keys())
    rows = parse_submission(_full_csv(), ids)
    store_submission(c, 555, rows, "h1")
    store_submission(c, 555, rows, "h2")
    active = c.execute("SELECT COUNT(*) n FROM submissions WHERE is_active=1").fetchone()["n"]
    assert active == 1
```

- [ ] **Step 2: Run test, verify fail**

Run: `pytest tests/test_handlers.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement** `wc2026bot/handlers.py`

```python
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
```

- [ ] **Step 4: Run test, verify pass**

Run: `pytest tests/test_handlers.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/handlers.py tests/test_handlers.py
git commit -m "feat: telegram command logic helpers"
```

---

### Task 11: Wire-up, main entrypoint, README

**Files:**
- Create: `wc2026bot/main.py`, `README.md`
- Test: full suite green + manual smoke run.

**Interfaces:**
- Consumes: everything above. No new public interfaces.

- [ ] **Step 1: Implement** `wc2026bot/main.py`

```python
import asyncio
import hashlib
import logging

import httpx
from telegram import Update
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          ContextTypes, filters)

from wc2026bot.config import load_settings
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams, by_espn_name, by_fd_name
from wc2026bot.validation import parse_submission, ValidationError
from wc2026bot.feeds.espn import EspnClient
from wc2026bot.feeds.footballdata import FootballDataClient
from wc2026bot.poller import run_poller
from wc2026bot import handlers, notify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wc2026bot")


def build_app():
    s = load_settings()
    conn = connect(s.db_path)
    init_db(conn)
    teams = load_teams("data/teams.csv")
    seed_teams(conn, teams)
    team_names = {t.zindi_id: t.country for t in teams.values()}
    valid_ids = set(teams.keys())
    http = httpx.AsyncClient(timeout=15)
    clients = [
        EspnClient(by_espn_name(teams), http),
        FootballDataClient(by_fd_name(teams), http, s.footballdata_key),
    ]

    async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        handlers.register_user(conn, update.effective_chat.id)
        await update.message.reply_text(handlers.cmd_start_text())

    async def help_cmd(update: Update, _ctx):
        await update.message.reply_text(handlers.cmd_start_text())

    async def me(update: Update, _ctx):
        await update.message.reply_text(
            handlers.me_text(conn, update.effective_chat.id))

    async def rank(update: Update, _ctx):
        await update.message.reply_text(handlers.rank_text(conn))

    async def team(update: Update, ctx):
        if not ctx.args:
            await update.message.reply_text("Usage: /team <ISO3>")
            return
        await update.message.reply_text(
            handlers.team_text(conn, update.effective_chat.id,
                               ctx.args[0], team_names))

    async def upload_doc(update: Update, _ctx):
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
            await update.message.reply_text(f"❌ {e}")
            return
        handlers.store_submission(
            conn, update.effective_chat.id, rows,
            hashlib.sha256(text.encode()).hexdigest())
        await update.message.reply_text(
            "✅ Submission stored. /me for your live standing.")

    app = Application.builder().token(s.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("team", team))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_doc))

    async def on_finished(match_ids: list[str]):
        for mid in match_ids:
            msg = notify.build_finish_message(conn, mid, team_names)
            for cid in notify.affected_users(conn, mid):
                try:
                    await app.bot.send_message(cid, msg)
                except Exception as e:  # noqa: BLE001
                    log.warning("push to %s failed: %s", cid, e)

    return app, conn, clients, on_finished


async def _run():
    app, conn, clients, on_finished = build_app()
    stop = asyncio.Event()
    async with app:
        await app.start()
        await app.updater.start_polling()
        poller_task = asyncio.create_task(
            run_poller(conn, clients, on_finished, stop))
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            stop.set()
            await poller_task
            await app.updater.stop()
            await app.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write README.md**

```markdown
# WC2026 Telegram Live Tracker

Live tracker for the Zindi World Cup 2026 Goal Prediction Challenge.

## Setup
    python -m venv .venv && . .venv/Scripts/activate
    pip install -r requirements.txt
    python scripts/build_teams_csv.py

## Run
    BOT_TOKEN=xxx DB_PATH=wc2026.db FOOTBALLDATA_KEY=yyy python -m wc2026bot.main

`FOOTBALLDATA_KEY` is optional (ESPN works keyless).

## Test
    pytest -q

## Deploy (Railway / Fly / Render)
Single always-on process. Set env vars `BOT_TOKEN`, `DB_PATH`,
optional `FOOTBALLDATA_KEY`. Long-polling — no public URL required.
Persist `DB_PATH` on a volume.
```

- [ ] **Step 3: Run full test suite**

Run: `pytest -q`
Expected: all tests pass.

- [ ] **Step 4: Smoke run (manual, needs a real bot token)**

```bash
BOT_TOKEN=<token> python -m wc2026bot.main
```
In Telegram: `/start`, upload `data/SampleSubmission.csv`, `/me`, `/rank`,
`/team AUT`. Confirm replies. Ctrl-C to stop.

- [ ] **Step 5: Commit**

```bash
git add wc2026bot/main.py README.md
git commit -m "feat: main entrypoint, poller wiring, README"
```

---

## Self-Review

**Spec coverage:**
- Multi-user public bot → Tasks 3, 10. ✅
- Multi-source feed + fallback → Task 7. ✅
- Polling state machine (dormant/pre/in-play/finalize) → Task 8 + 2-source via fallback. ✅
- Current-state RMSE + Macro F1 + normalization + combined + rank → Task 5, 9. ✅
- Commands (/start /upload /me /rank /today /yesterday /team /help) → Tasks 10, 11. ⚠️ `/today` and `/yesterday` are listed in spec; implemented as a follow-up (see gap below).
- Push on goal/finish → Task 8 (`on_finished`) + Task 9 + Task 11. Goal-level push is finish-level in v1 (see gap). 
- Upload validation rules → Task 4. ✅
- SQLite schema → Task 3. ✅
- Penalty shootout exclusion → relies on feed `fullTime` excluding shootouts (Football-Data `fullTime` already excludes behavior; ESPN `score` is regulation+ET). Documented assumption; revisit if a feed includes shootout in score.
- Testing (mock fixtures, simulated progression, eval unit tests) → Tasks 4–10. ✅

**Identified gaps (fold into Task 10/11 or a follow-up plan):**
1. `/today` and `/yesterday` commands — query `matches` by `kickoff_time` date. Small additions to `handlers.py` + `main.py`; add when match calendar is seeded.
2. **Goal-level push** (vs finish-level): v1 pushes on match finish. Live per-goal push needs score-delta detection in `poll_once` (compare new vs stored score for LIVE matches) and a `build_goal_message`. Add as Task 12 if desired.
3. **Authoritative round/stage**: ESPN doesn't label WC round cleanly. Seed a static fixture calendar (match_id → stage, kickoff) so `current_stage`, `/today`, and runner-up/champion derivation are correct. Recommended as Task 0.5 before live deployment.

**Placeholder scan:** none — all steps contain runnable code.

**Type consistency:** `MatchResult` defined once in `state.py`, reused by feeds/poller/tests. `UserScore` from `evaluation.py` used by `notify`/`handlers`. `ParsedRow` from `validation.py` used by `handlers`. Consistent.
```
