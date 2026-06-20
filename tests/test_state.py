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

def test_apply_result_unknown_stage_does_not_crash():
    c = _conn()
    # Use an unrecognized match_stage ("third_place" not in MATCH_STAGE_TO_REACHED)
    r = MatchResult("m1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                    "FINISHED", "third_place", "2026-06-15T18:00:00Z")
    # Should return True (newly finished) and not raise
    assert apply_result(c, r) is True
    # Goals should be recomputed
    aut = c.execute("SELECT actual_goals FROM teams_state WHERE team_id=?",
                    ("WC-2026_AUT",)).fetchone()["actual_goals"]
    assert aut == 2


def test_make_match_id_stable_across_orientation():
    from wc2026bot.state import make_match_id
    a = make_match_id("WC-2026_AUT", "WC-2026_BEL", "2026-06-15T18:00Z")
    b = make_match_id("WC-2026_BEL", "WC-2026_AUT", "2026-06-15T20:00Z")
    # same teams + same date -> same id regardless of home/away or time-of-day
    assert a == b
