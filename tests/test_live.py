"""Tests for the live source adapter + player matching (no network needed)."""

from match_charting_project.live import espn, players


def test_normalize_strips_accents_and_punctuation():
    assert players.normalize("Stéfanos Tsitsipás") == "stefanos tsitsipas"
    assert players.normalize("Soon-Woo Kwon") == "soon woo kwon"
    assert players.normalize("J.J. Wolf") == "j j wolf"


def test_match_player_exact_fuzzy_and_miss():
    uni = {"M": {players.normalize(n): n for n in
                 ("Alexander Shevchenko", "Roger Federer", "Soon Woo Kwon")}}
    assert players.match_player("Roger Federer", "M", uni) == "Roger Federer"
    assert players.match_player("Aleksandr Shevchenko", "M", uni) == "Alexander Shevchenko"
    assert players.match_player("SoonWoo Kwon", "M", uni) == "Soon Woo Kwon"
    assert players.match_player("Some Qualifier", "M", uni) is None


_RAW = {"events": [{"id": "188-2026", "name": "Wimbledon", "major": True, "groupings": [
    {"grouping": {"slug": "mens-singles"}, "competitions": [
        {"id": "m1", "round": {"displayName": "Final"},
         "status": {"type": {"state": "post", "shortDetail": "Final"}},
         "competitors": [
             {"athlete": {"displayName": "Champ Winner"}, "flag": {"alt": "Spain"},
              "winner": True, "linescores": [{"value": 6}, {"value": 7}]},
             {"athlete": {"displayName": "Runner Up"}, "winner": False,
              "linescores": [{"value": 3}, {"value": 6}]}]},
        {"id": "q1", "round": {"displayName": "Qualifying 1st Round"},
         "status": {"type": {"state": "post"}}, "competitors": [
             {"athlete": {"displayName": "Q A"}, "winner": True},
             {"athlete": {"displayName": "Q B"}, "winner": False}]}]},
    {"grouping": {"slug": "mens-doubles"}, "competitions": [
        {"id": "d1", "round": {"displayName": "Final"}, "status": {"type": {"state": "post"}},
         "competitors": [{"athlete": {"displayName": "X"}}, {"athlete": {"displayName": "Y"}}]}]},
]}]}


def test_parse_singles_maindraw_only():
    tours = espn.parse(_RAW)
    assert len(tours) == 1                          # doubles grouping ignored
    t = tours[0]
    assert (t.gender, t.tier, t.best_of) == ("M", "Grand Slam", 5)
    assert len(t.matches) == 1                      # qualifying round excluded
    m = t.matches[0]
    assert m.round_label == "Final" and m.state == "post"
    assert m.a.name == "Champ Winner" and m.a.winner and m.a.sets == [6, 7]
    assert m.a.country == "Spain"
