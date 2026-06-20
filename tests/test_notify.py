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
