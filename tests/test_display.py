from wc2026bot.feeds.footballdata import Scorer, StandingRow, GroupTable
from wc2026bot.handlers import scorers_text, standings_text


def test_scorers_text_lists_ranked_players():
    s = [Scorer("Foo Bar", "Austria", 4), Scorer("Baz Qux", "Belgium", 3)]
    txt = scorers_text(s)
    assert "1." in txt and "Foo Bar" in txt and "4" in txt
    assert "Belgium" in txt


def test_scorers_text_empty():
    assert "no" in scorers_text([]).lower()


def test_standings_text_renders_group():
    g = [GroupTable("GROUP_A", [
        StandingRow(1, "Austria", 2, 6, 4, 5),
        StandingRow(2, "Belgium", 2, 3, 0, 2)])]
    txt = standings_text(g, None)
    assert "GROUP_A" in txt or "Group A" in txt
    assert "Austria" in txt and "6" in txt


def test_standings_text_filters_one_group():
    g = [GroupTable("GROUP_A", [StandingRow(1, "Austria", 2, 6, 4, 5)]),
         GroupTable("GROUP_B", [StandingRow(1, "Brazil", 2, 6, 4, 5)])]
    txt = standings_text(g, "a")
    assert "Austria" in txt
    assert "Brazil" not in txt


def test_standings_text_empty():
    assert "no" in standings_text([], None).lower()
