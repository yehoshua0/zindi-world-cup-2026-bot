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
