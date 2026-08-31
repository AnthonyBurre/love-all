"""Tests for the live source adapter + player matching (no network needed)."""

import json
from datetime import date, datetime, timedelta, timezone

import duckdb

from match_charting_project.live import brackets, espn, feeds, levels, players


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


def test_parse_seats_sides_by_espn_bracket_order_not_array_order():
    # ESPN's `order` (1 = top of the box, 2 = below) is the feed's own draw position, and
    # the competitors array is often not in it — here it arrives 2 then 1. Side a must be
    # the order-1 player regardless.
    raw = {"events": [{"id": "189-2026", "name": "US Open", "major": True, "groupings": [
        {"grouping": {"slug": "mens-singles"}, "competitions": [
            {"id": "m1", "round": {"displayName": "Round 2"},
             "status": {"type": {"state": "pre"}}, "competitors": [
                 {"athlete": {"displayName": "Lower Half"}, "order": 2},
                 {"athlete": {"displayName": "Upper Half"}, "order": 1}]},
            {"id": "m2", "round": {"displayName": "Round 2"},
             "status": {"type": {"state": "pre"}}, "competitors": [
                 {"athlete": {"displayName": "First Listed"}},
                 {"athlete": {"displayName": "Second Listed"}}]}]}]}]}
    ms = {m.id: m for m in espn.parse(raw)[0].matches}
    assert (ms["m1"].a.name, ms["m1"].b.name) == ("Upper Half", "Lower Half")
    assert (ms["m2"].a.name, ms["m2"].b.name) == ("First Listed", "Second Listed")  # no order: as-is


def test_parse_carries_the_per_set_winner_and_leaves_a_live_set_undecided():
    # A suspended five-setter, resumed as a fresh "Scheduled" slot: four decided sets
    # each carry a winner flag, the fifth (4-3, still on court) carries none on either
    # side. The site keys set-score bold off this, so the live set stays unbolded.
    raw = {"events": [{"id": "189-2026", "name": "US Open", "major": True, "groupings": [
        {"grouping": {"slug": "mens-singles"}, "competitions": [
            {"id": "s1", "round": {"displayName": "Round 1"},
             "status": {"type": {"state": "pre", "shortDetail": "8/31 - 12:30 PM"}},
             "competitors": [
                 {"athlete": {"displayName": "Rei Sakamoto"}, "linescores": [
                     {"value": 6, "winner": True}, {"value": 6, "winner": False},
                     {"value": 6, "winner": True}, {"value": 3, "winner": False},
                     {"value": 4}]},
                 {"athlete": {"displayName": "Aleksandar Vukic"}, "linescores": [
                     {"value": 4, "winner": False}, {"value": 7, "winner": True},
                     {"value": 4, "winner": False}, {"value": 6, "winner": True},
                     {"value": 3}]}]}]}]}]}
    m = espn.parse(raw)[0].matches[0]
    assert m.a.sets == [6, 6, 6, 3, 4]
    assert m.a.set_wins == [True, False, True, False, None]
    assert m.b.set_wins == [False, True, False, True, None]
    # Round through serialize: the flag rides in the payload the site reads.
    payload = brackets.serialize(espn.parse(raw)[0], use_fixture=False)
    side = payload["rounds"][0]["matches"][0]["a"]
    assert side["set_wins"] == [True, False, True, False, None]


# --- tour level: the 500 roster vs. the name heuristics --------------------------------

def _event(id, name, venue, slug="mens-singles", major=False, date="2026-07-27T14:00Z"):
    """A minimal one-match scoreboard event, enough to reach espn.parse's tier decision.

    The date matters: the calendar feed joins on venue city *and* week, because a city can
    host two events a season at different levels.
    """
    return {"id": id, "name": name, "major": major, "date": date,
            "venue": {"displayName": venue},
            "groupings": [{"grouping": {"slug": slug}, "competitions": [
                {"id": f"{id}-c", "round": {"displayName": "Final"},
                 "status": {"type": {"state": "pre", "shortDetail": "1:00 PM"}},
                 "competitors": [{"athlete": {"displayName": "A One"}},
                                 {"athlete": {"displayName": "B Two"}}]}]}]}


def _cal(*entries):
    """A stand-in calendar feed: (gender, city, tier, month) tuples."""
    return {"season": 2026,
            "events": [{"gender": g, "city": c, "tier": t, "month": m,
                        "event": c + " Open", "surface": "Hard", "indoor": False,
                        "draw_size": None, "singles_pages": []}
                       for g, c, t, m in entries]}


def _tiers(*events, cal=None):
    return {(t.gender, t.name): t.tier
            for t in espn.parse({"events": list(events)}, cal=cal or _cal())}


CAL_2026 = _cal(("M", "Washington", "ATP 500", 7), ("W", "Washington DC", "WTA 500", 7),
                ("M", "Los Cabos", "ATP 250", 7), ("W", "Rome", "WTA 1000", 5),
                ("M", "Doha", "ATP 500", 2), ("M", "Hamburg", "ATP 500", 5),
                ("M", "Dubai", "ATP 500", 2), ("W", "Dubai", "WTA 1000", 2))


def test_parse_serves_500s_and_drops_the_rest_of_the_tour():
    got = _tiers(
        _event("888-2026", "Mubadala DC Open", "Washington, USA"),            # ATP 500
        _event("888-2026", "Mubadala DC Open", "Washington, USA", "womens-singles"),
        _event("424-2026", "Mifel Tennis Open by Telcel Oppo", "Los Cabos, Mexico"),  # 250
        _event("1017-2026", "ATV Bancomat Tennis Open", "Rome, Italy", "womens-singles"),
        cal=CAL_2026)
    assert got == {("M", "Mubadala DC Open"): levels.TOUR_500,
                   ("W", "Mubadala DC Open"): levels.TOUR_500}


def test_a_125_sharing_a_city_with_a_1000_is_not_promoted():
    # The calendar covers 250 and up, so a WTA 125 is absent from it — and the Rome 125
    # matches the Rome 1000 on city exactly. Only the week separates them: May vs July.
    in_july = _tiers(_event("1017-2026", "ATV Bancomat Tennis Open", "Rome, Italy",
                            "womens-singles", date="2026-07-20T10:00Z"), cal=CAL_2026)
    assert in_july == {}                            # dropped, not served as a 1000

    in_may = _tiers(_event("414-2026", "Internazionali BNL d'Italia", "Rome, Italy",
                           "womens-singles", date="2026-05-06T10:00Z"), cal=CAL_2026)
    assert list(in_may.values()) == ["Masters / WTA 1000"]


def test_calendar_beats_the_1000_city_heuristics():
    # Doha and Hamburg both trip the 1000 city lists — as an old Masters stop, or because
    # the women's event in the same city really is a 1000. The calendar wins.
    got = _tiers(_event("119-2026", "Qatar ExxonMobil Open", "Doha, Qatar",
                        date="2026-02-16T10:00Z"),
                 _event("942-2026", "Bitpanda Hamburg Open", "Hamburg, Germany",
                        date="2026-05-18T10:00Z"), cal=CAL_2026)
    assert set(got.values()) == {levels.TOUR_500}


def test_one_city_can_straddle_levels_by_tour():
    # Dubai is ATP 500 but WTA 1000, in the same city in the same week.
    got = _tiers(_event("25-2026", "Dubai Duty Free Tennis Championships", "Dubai, UAE",
                        date="2026-02-23T10:00Z"),
                 _event("25-2026", "Dubai Duty Free Tennis Championships", "Dubai, UAE",
                        "womens-singles", date="2026-02-23T10:00Z"), cal=CAL_2026)
    assert got[("M", "Dubai Duty Free Tennis Championships")] == levels.TOUR_500
    assert got[("W", "Dubai Duty Free Tennis Championships")] == "Masters / WTA 1000"


def test_parse_carries_the_venue_city():
    t = espn.parse({"events": [_event("888-2026", "Mubadala DC Open", "Washington, USA")]},
                   cal=CAL_2026)[0]
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


# --- calendar freshness ----------------------------------------------------------------

def _cal_doc(fetched, season=None):
    return {"season": season or date.today().year, "fetched": fetched,
            "events": [{"event": "Canadian Open", "gender": "M", "city": "Montreal",
                        "tier": "ATP 1000", "month": 8, "singles_pages": []}]}


def _iso(**ago):
    return (datetime.now(timezone.utc) - timedelta(**ago)).isoformat(timespec="minutes")


def test_a_calendar_read_within_the_day_is_fresh():
    assert feeds.calendar_stale(_cal_doc(_iso(hours=3))) is False


def test_a_calendar_read_days_ago_is_stale_even_in_its_own_season():
    # The regression this gate exists for: the cache is the right season and parses fine,
    # but predates the National Bank Open draw — so it links no draw page for it, and the
    # season check it replaced would have held it until January.
    assert feeds.calendar_stale(_cal_doc(_iso(days=3))) is True


def test_last_seasons_calendar_is_stale():
    assert feeds.calendar_stale(_cal_doc(_iso(minutes=1), season=date.today().year - 1))


def test_an_empty_or_undated_calendar_is_stale():
    assert feeds.calendar_stale({})                          # no cache at all
    assert feeds.calendar_stale({"season": date.today().year, "events": []})
    assert feeds.calendar_stale(_cal_doc(None))              # written without a stamp
    assert feeds.calendar_stale(_cal_doc("not a timestamp"))


def test_a_naive_timestamp_is_read_as_utc():
    # Older caches were stamped without an offset; those must not blow up the comparison.
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="minutes")
    assert feeds.calendar_stale(_cal_doc(naive)) is False


# --- event labels ----------------------------------------------------------------------

CAL_CANADA = {"season": 2026, "events": [
    {"gender": "M", "event": "Canadian Open", "city": "Montreal", "tier": "ATP 1000",
     "surface": "Hard", "indoor": False, "month": 8, "singles_pages": []},
    {"gender": "W", "event": "Canadian Open", "city": "Toronto", "tier": "WTA 1000",
     "surface": "Hard", "indoor": False, "month": 8, "singles_pages": []},
]}


def test_event_meta_names_an_event_the_way_people_do():
    # The feed calls it after the title sponsor and files both draws under one venue. The
    # calendar knows the name people use, the per-tour level, and that the men are in
    # Montreal while the women are in Toronto — same event, two cities.
    sponsor = "National Bank Open presented by Rogers"
    men = feeds.event_meta_for("Toronto", sponsor, "M", 8, CAL_CANADA)
    women = feeds.event_meta_for("Toronto", sponsor, "W", 8, CAL_CANADA)
    assert men["common_name"] == women["common_name"] == "Canadian Open"
    assert (men["level"], men["venue"]) == ("ATP 1000", "Montreal")
    assert (women["level"], women["venue"]) == ("WTA 1000", "Toronto")
    assert men["surface"] == "Hard" and men["indoor"] is False


def test_event_meta_is_empty_when_the_calendar_cannot_place_the_event():
    # A stop the calendar doesn't cover leaves the site showing the feed's name alone,
    # which is the state this replaced — never a line of half-filled labels.
    assert feeds.event_meta_for("Nowhere", "Some New Open", "M", 3, CAL_CANADA) == {}
    assert feeds.event_meta_for("Toronto", "National Bank Open", "M", 8,
                                {"season": 2026, "events": []}) == {}


def test_serialize_carries_the_event_labels_so_the_archive_freezes_them():
    t = _tour([_m("f", 100, "Final", "Ann", "Bea")])
    t.name, t.city, t.gender = "National Bank Open presented by Rogers", "Toronto", "M"
    for m in t.matches:
        m.date = "2026-08-05T18:00Z"

    assert brackets.serialize(t, use_fixture=False)["event"] == {}   # no calendar cached
    feeds.CALENDAR.write_text(json.dumps(CAL_CANADA))                # conftest's tmp path
    payload = brackets.serialize(t, use_fixture=False)
    assert payload["event"]["common_name"] == "Canadian Open"
    assert payload["event"]["level"] == "ATP 1000"
    assert payload["name"] == t.name                    # the sponsor's name is still there


# --- the request budget: poll while a draw is being played, probe daily between ----------

def _scoreboard(start: datetime, end: datetime) -> dict:
    """A scoreboard carrying one event's window — all `_playing` reads."""
    return {"events": [{"id": "421-2026", "name": "National Bank Open",
                        "date": start.isoformat().replace("+00:00", "Z"),
                        "endDate": end.isoformat().replace("+00:00", "Z")}]}


def _seed_cache(tmp_path, doc: dict, fetched_ago: timedelta) -> None:
    stamp = (datetime.now(timezone.utc) - fetched_ago).isoformat(timespec="minutes")
    (tmp_path / "live").mkdir(exist_ok=True)
    (tmp_path / "live" / "atp_scoreboard.json").write_text(
        json.dumps({**doc, "_fetched_at": stamp}))


def _attempts(monkeypatch) -> list:
    """Record outbound attempts without making one. ``_fetch`` catches a failed request and
    falls back to the cache, so the count — not a raised error — is what tells us whether a
    request was spent."""
    seen = []

    def spy(req, *a, **k):
        seen.append(req.full_url)
        raise OSError("no network in tests")

    monkeypatch.setattr(espn.urllib.request, "urlopen", spy)
    return seen


def test_between_events_a_recent_probe_costs_no_request(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed_cache(tmp_path, _scoreboard(now - timedelta(days=20), now - timedelta(days=6)),
                fetched_ago=timedelta(hours=3))
    seen = _attempts(monkeypatch)

    raw, stamp = espn._fetch("atp")               # serves the cache, unchanged
    assert seen == []                             # the point: no request at all
    assert raw["events"][0]["id"] == "421-2026"
    assert stamp                                  # dated by the fetch, not by this build


def test_between_events_we_still_probe_once_a_day(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed_cache(tmp_path, _scoreboard(now - timedelta(days=20), now - timedelta(days=6)),
                fetched_ago=timedelta(days=1, hours=1))
    seen = _attempts(monkeypatch)

    espn._fetch("atp")                            # a probe is due — this is how a new event
    assert len(seen) == 1                         # gets noticed at all


def test_a_draw_in_progress_is_polled_every_run(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    _seed_cache(tmp_path, _scoreboard(now - timedelta(days=2), now + timedelta(days=5)),
                fetched_ago=timedelta(minutes=2))  # probed moments ago, still polls
    seen = _attempts(monkeypatch)

    espn._fetch("atp")
    assert len(seen) == 1


def test_with_no_cache_at_all_we_fetch(tmp_path, monkeypatch):
    seen = _attempts(monkeypatch)
    try:
        espn._fetch("atp")                        # nothing cached to fall back to
    except OSError:
        pass
    assert len(seen) == 1


def test_the_grace_margin_keeps_polling_until_the_final_is_archived():
    now = datetime.now(timezone.utc)
    ended = _scoreboard(now - timedelta(days=14), now - timedelta(hours=6))
    assert espn._playing(ended, now) is True       # inside the grace day, still polling
    assert espn._playing(_scoreboard(now - timedelta(days=20),
                                     now - timedelta(days=3)), now) is False


def test_an_unreadable_window_polls_rather_than_going_dark():
    now = datetime.now(timezone.utc)
    assert espn._playing({}, now) is True                          # no events
    assert espn._playing({"events": [{"id": "x"}]}, now) is True   # undated
    assert espn._playing({"events": [{"date": "soon", "endDate": "later"}]}, now) is True


# --- charted coverage, whole and by season ---------------------------------------------
# The panel prints both: a total per player, and a bar per season under it. They come from
# one SQL body with two GROUP BYs (players._COVERAGE_ROWS) precisely because a second copy
# of the player1/player2 union is how the two come to disagree — and a breakdown that does
# not add up to the total beside it is wrong in a way nothing on the page can show.
def _cov_db():
    con = duckdb.connect()
    con.execute("CREATE TABLE matches (match_id VARCHAR, gender VARCHAR, "
                "player1 VARCHAR, player2 VARCHAR, year INTEGER)")
    con.execute("CREATE TABLE points (match_id VARCHAR, svr INTEGER)")
    rows = [("m1", "M", "Ann", "Bo", 2023, 4), ("m2", "M", "Ann", "Cy", 2023, 3),
            ("m3", "M", "Ann", "Bo", 2025, 5),
            # A column-shifted row: charted, counted in the total, unplaceable on an axis.
            ("m4", "M", "Ann", "Bo", None, 2)]
    for mid, g, p1, p2, yr, n in rows:
        con.execute("INSERT INTO matches VALUES (?, ?, ?, ?, ?)", [mid, g, p1, p2, yr])
        for _ in range(n):
            con.execute("INSERT INTO points VALUES (?, 1)", [mid])
        con.execute("INSERT INTO points VALUES (?, 0)", [mid])   # not a served point
    return con


def test_coverage_by_year_adds_up_to_the_totals_it_is_drawn_under():
    con = _cov_db()
    total = players.coverage(con)[("M", "Ann")]
    by_year = {y: (m, p) for g, pl, y, m, p in players.coverage_by_year(con)
               if (g, pl) == ("M", "Ann")}
    assert by_year == {2023: (2, 7), 2025: (1, 5)}
    # The dated seasons account for the whole of the total bar the one undated match, and
    # the span the chart is drawn across is the one the totals line claims.
    assert sum(m for m, _ in by_year.values()) == total["matches"] - 1
    assert sum(p for _, p in by_year.values()) == total["points"] - 2
    assert (min(by_year), max(by_year)) == (total["year_min"], total["year_max"])


def test_coverage_by_year_drops_matches_with_no_year():
    con = _cov_db()
    assert all(y is not None for _g, _p, y, _m, _pt in players.coverage_by_year(con))
