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
