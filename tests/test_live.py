"""Tests for the live source adapter + player matching (no network needed)."""

from match_charting_project.live import brackets, espn, levels, players


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


# --- tour level: the 500 roster vs. the name heuristics --------------------------------

def _event(id, name, venue, slug="mens-singles", major=False):
    """A minimal one-match scoreboard event, enough to reach espn.parse's tier decision."""
    return {"id": id, "name": name, "major": major, "venue": {"displayName": venue},
            "groupings": [{"grouping": {"slug": slug}, "competitions": [
                {"id": f"{id}-c", "round": {"displayName": "Final"},
                 "status": {"type": {"state": "pre", "shortDetail": "1:00 PM"}},
                 "competitors": [{"athlete": {"displayName": "A One"}},
                                 {"athlete": {"displayName": "B Two"}}]}]}]}


def _tiers(*events):
    return {(t.gender, t.name): t.tier for t in espn.parse({"events": list(events)})}


def test_parse_serves_rostered_500s_and_drops_the_rest_of_the_tour():
    got = _tiers(
        _event("888-2026", "Mubadala DC Open", "Washington, USA"),            # ATP 500
        _event("888-2026", "Mubadala DC Open", "Washington, USA", "womens-singles"),
        _event("424-2026", "Mifel Tennis Open by Telcel Oppo", "Los Cabos, Mexico"),  # 250
        _event("1017-2026", "ATV Bancomat Tennis Open", "Rome, Italy", "womens-singles"),
    )
    assert got == {("M", "Mubadala DC Open"): levels.TOUR_500,
                   ("W", "Mubadala DC Open"): levels.TOUR_500}
    # The 250 and the WTA 125 are filtered out entirely — and note the 125 plays *Rome*,
    # so a city-keyed roster would have promoted it to a 1000.


def test_roster_beats_the_1000_city_heuristics():
    # Doha, Dubai and Hamburg all trip the 1000 city lists — as an old Masters stop, or
    # because the women's event at the same city really is a 1000. The roster wins.
    got = _tiers(_event("119-2026", "Qatar ExxonMobil Open", "Doha, Qatar"),
                 _event("942-2026", "Bitpanda Hamburg Open", "Hamburg, Germany"))
    assert set(got.values()) == {levels.TOUR_500}


def test_one_event_id_can_straddle_levels_by_tour():
    # Dubai is ATP 500 but WTA 1000, under a single shared ESPN event id.
    got = _tiers(_event("25-2026", "Dubai Duty Free Tennis Championships", "Dubai, UAE"),
                 _event("25-2026", "Dubai Duty Free Tennis Championships", "Dubai, UAE",
                        "womens-singles"))
    assert got[("M", "Dubai Duty Free Tennis Championships")] == levels.TOUR_500
    assert got[("W", "Dubai Duty Free Tennis Championships")] == "Masters / WTA 1000"


def test_parse_carries_the_venue_city():
    t = espn.parse({"events": [_event("888-2026", "Mubadala DC Open", "Washington, USA")]})[0]
    assert t.city == "Washington"               # not the sponsor's name for it
    assert brackets.serialize(t)["city"] == "Washington"


def test_tourn_key_bridges_feed_city_and_db_name():
    # The db files these as cities, sometimes with a Masters suffix; both sides key here.
    assert players.tourn_key("Cincinnati Masters") == players.tourn_key("Cincinnati")
    assert players.tourn_key("Monte Carlo Masters") == players.tourn_key("Monte-Carlo")
    assert players.tourn_key("Canada Masters") == players.tourn_key("Montreal")
    assert players.tourn_key("Toronto") == players.tourn_key("Montreal")
    assert players.tourn_key("French Open") == players.tourn_key("Roland Garros")
    assert players.tourn_key("Washington") != players.tourn_key("Mubadala DC Open")


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
