from wc2026bot.teams import load_teams, by_espn_name, by_fd_name

def test_load_teams_has_48():
    teams = load_teams("data/teams.csv")
    assert len(teams) == 48
    assert teams["WC-2026_AUT"].country == "Austria"
    assert teams["WC-2026_AUT"].iso3 == "AUT"

def test_reverse_indexes_unique():
    teams = load_teams("data/teams.csv")
    assert len(by_espn_name(teams)) == 48
    assert len(by_fd_name(teams)) == 48
