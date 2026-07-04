"""Tests for the live source adapter + player matching (no network needed)."""

from match_charting_project.live import brackets, espn, players


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


def _m(id, rank, label, a, b, winner=None):
    def side(n):
        return espn.Side(name=n, country=None, winner=(n == winner), sets=[])
    return espn.Match(id=id, round_rank=rank, round_label=label,
                      state="post" if winner else "pre", detail="", a=side(a), b=side(b))


def _tour(matches):
    return espn.Tournament(id="t", name="Test Open", tier="Grand Slam", gender="M",
                           best_of=5, matches=matches)


def test_bracket_linkage_and_ordering():
    # R1 played; R2 half-resolved; final TBD. Feed order deliberately scrambled.
    t = _tour([
        _m("f", 100, "Final", "TBD", "TBD"),
        _m("s1", 99, "Semifinal", "Ann", "Cara"),          # from r1a + r1c
        _m("s2", 99, "Semifinal", "Eve", "TBD"),           # from r1e; other feeder unknown
        _m("r1c", 1, "Round 1", "Cara", "Dana", winner="Cara"),
        _m("r1a", 1, "Round 1", "Ann", "Bea", winner="Ann"),
        _m("r1g", 1, "Round 1", "Gail", "Hope", winner="Gail"),
        _m("r1e", 1, "Round 1", "Eve", "Faye", winner="Eve"),
    ])
    rounds = brackets.rounds(t)
    assert [r["label"] for r in rounds] == ["Round 1", "Semifinal", "Final"]

    feeds = {m.id: m.feeds for r in rounds for m in r["matches"]}
    assert feeds["r1a"] == "s1" and feeds["r1c"] == "s1"    # winners found in s1
    assert feeds["r1e"] == "s2"
    assert feeds["r1g"] is None                             # opponent slot still TBD
    assert feeds["s1"] is None and feeds["s2"] is None      # final is TBD-TBD
    assert feeds["f"] is None

    # Linked R1 matches are reordered adjacent to their semifinal; unlinked sorts last.
    assert [m.id for m in rounds[0]["matches"]] == ["r1c", "r1a", "r1e", "r1g"]


def test_bracket_linkage_duplicate_name_claims_nothing():
    # The same name in two next-round matches is ambiguous -> no link, not a wrong link.
    t = _tour([
        _m("s1", 99, "Semifinal", "Ann", "TBD"),
        _m("s2", 99, "Semifinal", "Ann", "TBD"),
        _m("r1", 1, "Round 1", "Ann", "Bea", winner="Ann"),
    ])
    rounds = brackets.rounds(t)
    (r1,) = rounds[0]["matches"]
    assert r1.feeds is None
