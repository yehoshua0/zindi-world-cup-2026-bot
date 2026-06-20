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
