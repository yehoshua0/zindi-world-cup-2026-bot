import hashlib
import pytest
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.validation import parse_submission
from wc2026bot.handlers import (register_user, store_submission, me_text,
                                rank_text, set_display_name, display_name,
                                needs_name_msg, SetNameError, matches_on_text)

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

def test_setname_and_gate():
    c = _conn()
    assert needs_name_msg(c, 555) is not None  # no name yet -> gated
    set_display_name(c, 555, "Zuno")
    assert display_name(c, 555) == "Zuno"
    assert needs_name_msg(c, 555) is None  # gate cleared

def test_setname_unique_case_insensitive():
    c = _conn()
    set_display_name(c, 1, "Champion")
    with pytest.raises(SetNameError, match="taken"):
        set_display_name(c, 2, "champion")

def test_setname_same_user_can_rename():
    c = _conn()
    set_display_name(c, 1, "Old")
    set_display_name(c, 1, "New")  # not blocked by own previous name
    assert display_name(c, 1) == "New"

def test_setname_length_validation():
    c = _conn()
    with pytest.raises(SetNameError):
        set_display_name(c, 1, "x")  # too short

def test_rank_shows_display_name():
    c = _conn(); register_user(c, 555)
    set_display_name(c, 555, "Zuno")
    rows = parse_submission(_full_csv(), set(load_teams("data/teams.csv").keys()))
    store_submission(c, 555, rows, "h1")
    out = rank_text(c)
    assert "Zuno" in out and "user " not in out

def test_rank_excludes_unnamed_users():
    c = _conn()
    ids = set(load_teams("data/teams.csv").keys())
    rows = parse_submission(_full_csv(), ids)
    register_user(c, 100)  # no display_name
    store_submission(c, 100, rows, "h1")
    assert rank_text(c) == "No submissions yet."  # nobody named -> empty board
    set_display_name(c, 200, "Named")
    store_submission(c, 200, rows, "h2")
    out = rank_text(c)
    assert "Named" in out and "user " not in out

def test_matches_on_text():
    c = _conn()
    names = {t.zindi_id: t.country for t in load_teams("data/teams.csv").values()}
    ha, aw = list(names)[0], list(names)[1]
    c.execute("INSERT INTO matches(match_id, home_team_id, away_team_id, "
              "home_score, away_score, status, match_stage, kickoff_time) "
              "VALUES ('m1',?,?,2,1,'FINISHED','group','2026-06-21T18:00:00Z')",
              (ha, aw))
    c.execute("INSERT INTO matches(match_id, home_team_id, away_team_id, "
              "status, match_stage, kickoff_time) "
              "VALUES ('m2',?,?,'SCHEDULED','group','2026-06-21T21:00:00Z')",
              (ha, aw))
    c.commit()
    out = matches_on_text(c, "2026-06-21", names, "today")
    assert "🏁" in out and "2-1" in out and "⏰ 21:00" in out
    assert matches_on_text(c, "2026-06-20", names, "yesterday") \
        == "No matches yesterday (2026-06-20)."
