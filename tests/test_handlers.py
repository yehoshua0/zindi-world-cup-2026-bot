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
