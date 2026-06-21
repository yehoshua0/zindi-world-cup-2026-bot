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


def test_events_and_snapshots_tables_exist(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_db(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "events" in tables
    assert "leaderboard_snapshots" in tables
