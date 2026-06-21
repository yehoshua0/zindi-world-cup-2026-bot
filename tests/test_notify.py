from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams
from wc2026bot.state import MatchResult, apply_result
from wc2026bot.notify import (user_metrics, cohort_scores, affected_users,
                              personalized_messages)

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

def _names(c):
    return {t: c.execute("SELECT country FROM teams_state WHERE team_id=?",
            (t,)).fetchone()["country"] for t in
            (r["team_id"] for r in c.execute("SELECT team_id FROM teams_state"))}

def test_personalized_finish_message_includes_pick_and_rank():
    c, sid = _setup()
    apply_result(c, MatchResult("espn-1", "WC-2026_AUT", "WC-2026_BEL", 2, 1,
                 "FINISHED", "group", "2026-06-15T18:00:00Z"))
    msgs = personalized_messages(c, "espn-1", _names(c), kind="finish")
    assert len(msgs) == 1
    chat_id, text = msgs[0]
    assert chat_id == 111
    assert "Austria" in text and "Belgium" in text
    assert "2 - 1" in text
    assert "10.0" in text          # user's AUT goal pick surfaced
    assert "rank" in text.lower()

def test_personalized_goal_message_has_goal_header():
    c, sid = _setup()
    apply_result(c, MatchResult("espn-1", "WC-2026_AUT", "WC-2026_BEL", 1, 0,
                 "LIVE", "group", "2026-06-15T18:00:00Z"))
    msgs = personalized_messages(c, "espn-1", _names(c), kind="goal")
    assert len(msgs) == 1
    _cid, text = msgs[0]
    assert "GOAL" in text

def test_no_messages_for_unaffected_match():
    c, sid = _setup()
    # match between two teams; user predicted all teams, so still affected.
    # Use a match with teams the user has no prediction for: none exist (48 full),
    # so instead drop the user's predictions to simulate no active submission.
    c.execute("UPDATE submissions SET is_active=0")
    c.commit()
    apply_result(c, MatchResult("espn-1", "WC-2026_AUT", "WC-2026_BEL", 1, 1,
                 "FINISHED", "group", "2026-06-15T18:00:00Z"))
    assert personalized_messages(c, "espn-1", _names(c), kind="finish") == []
