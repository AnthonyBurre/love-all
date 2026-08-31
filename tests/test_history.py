"""The completed-draw archive: completion detection, accumulate-once, retention, and the
per-match charted-annotation gate (only flip a finished draw to per-match shading once it
has any charting)."""

from datetime import date

from match_charting_project.live import history
from match_charting_project.site import build_brackets


def _side(n, w):
    return {"name": n, "country": None, "winner": w, "sets": [], "seed": None}


def _match(id, a, b, wa=False, wb=False, state="post"):
    return {"id": id, "state": state, "detail": "", "feeds": None, "placeholder": False,
            "a": _side(a, wa), "b": _side(b, wb)}


def _tour(id, gender, rounds, tier="Grand Slam", name="Wimbledon"):
    return {"id": id, "name": name, "tier": tier, "gender": gender, "best_of": 5,
            "slotted": False, "rounds": rounds}


def _final(a, b, wa=False, wb=True, state="post"):
    return [{"rank": 100, "label": "Final", "matches": [_match("f", a, b, wa, wb, state)]}]


def test_is_complete():
    assert history.is_complete(_final("A", "B", wb=True))
    assert not history.is_complete(_final("A", "B", wa=False, wb=False))   # no winner
    assert not history.is_complete(_final("A", "B", state="pre"))          # not played
    assert not history.is_complete([])


def test_archive_adds_completed_once_and_skips_unfinished():
    store = []
    done = _tour("100", "M", _final("A", "B"))
    live = _tour("200", "M", _final("C", "D", state="pre"))    # final not played
    assert history.archive([done, live], store, today=date(2026, 7, 15)) == 1
    assert [(e["id"], e["completed"], e["year"]) for e in store] == [("100", True, 2026)]

    # A second pass must not duplicate the frozen snapshot.
    assert history.archive([done], store, today=date(2026, 7, 15)) == 0
    assert len(store) == 1


def test_prune_keeps_recent_slams_plus_newest_event():
    today = date(2026, 7, 15)
    store = [
        {"id": "recent", "gender": "M", "tier": "Grand Slam", "year": 2025,
         "archived_at": "2025-07-13T00:00+00:00"},
        {"id": "old-slam", "gender": "M", "tier": "Grand Slam", "year": 2020,
         "archived_at": "2020-09-13T00:00+00:00"},
        {"id": "newest-1000", "gender": "W", "tier": "Masters / WTA 1000", "year": 2026,
         "archived_at": "2026-07-14T00:00+00:00"},
    ]
    kept = {(e["id"], e["gender"]) for e in history.prune(store, today)}
    assert kept == {("recent", "M"), ("newest-1000", "W")}   # old slam dropped; 1000 is newest


def _archived(id, tier, stamp, gender="M", year=2026):
    return {"id": id, "gender": gender, "tier": tier, "year": year, "archived_at": stamp}


def test_prune_keeps_two_finished_events_per_non_slam_tier():
    today = date(2026, 8, 20)
    store = [
        _archived("slam", "Grand Slam", "2026-07-13T00:00+00:00", year=2026),
        _archived("500-a", "ATP / WTA 500", "2026-08-17T00:00+00:00"),   # newest 500
        _archived("500-b", "ATP / WTA 500", "2026-08-10T00:00+00:00"),
        _archived("500-c", "ATP / WTA 500", "2026-08-03T00:00+00:00"),   # third: aged out
        _archived("1000-a", "Masters / WTA 1000", "2026-08-16T00:00+00:00"),
    ]
    kept = {e["id"] for e in history.prune(store, today)}
    # Two newest 500s survive; the 1000 is counted in its own tier, so two fresher 500s
    # can't evict it.
    assert kept == {"slam", "500-a", "500-b", "1000-a"}


def test_prune_retires_a_combined_event_by_both_genders_at_once():
    today = date(2026, 8, 20)
    store = [
        _archived("500-a", "ATP / WTA 500", "2026-08-17T00:00+00:00", gender="M"),
        _archived("500-a", "ATP / WTA 500", "2026-08-17T00:00+00:00", gender="W"),
        _archived("500-b", "ATP / WTA 500", "2026-08-10T00:00+00:00", gender="M"),
        _archived("500-b", "ATP / WTA 500", "2026-08-10T00:00+00:00", gender="W"),
        _archived("500-c", "ATP / WTA 500", "2026-08-03T00:00+00:00", gender="M"),
    ]
    kept = history.prune(store, today)
    # Retention counts events, not rows: two events = four entries, not two.
    assert {(e["id"], e["gender"]) for e in kept} == {
        ("500-a", "M"), ("500-a", "W"), ("500-b", "M"), ("500-b", "W")}


def test_annotate_finds_charting_under_the_venue_city():
    # The db files this one as 'Washington'; the feed calls it 'Mubadala DC Open'.
    charted = {("M", 2026, "washington", frozenset(("a one", "b two"))): ("MID-9", "a one")}
    t = _tour("888-2026", "M", _final("A One", "B Two"), tier="ATP / WTA 500",
              name="Mubadala DC Open")
    t["city"] = "Washington"
    t["completed"], t["year"], t["season"] = True, 2026, 2026
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    m = t["rounds"][0]["matches"][0]
    assert (m["charted"], m["chart_id"]) == (True, "MID-9")


def test_annotate_still_finds_slams_by_name_not_city():
    # A slam's city ('London') is the wrong key — the db knows it as 'Wimbledon'.
    charted = {("M", 2026, "wimbledon", frozenset(("a one", "b two"))): ("MID-1", "a one")}
    t = _tour("188-2026", "M", _final("A One", "B Two"))
    t["city"] = "London"
    t["completed"], t["year"], t["season"] = True, 2026, 2026
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    assert t["rounds"][0]["matches"][0]["chart_id"] == "MID-1"


def test_annotate_charted_gate():
    charted = {("M", 2025, "wimbledon", frozenset(("a one", "b two"))): ("MID-1", "a one")}
    t = _tour("w", "M", [{"rank": 100, "label": "Final", "matches": [
        _match("m1", "A One", "B Two"),        # in the charted set
        _match("m2", "C Three", "D Four"),     # not charted
    ]}])
    t["completed"], t["year"], t["season"] = True, 2025, 2025
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    ms = t["rounds"][0]["matches"]
    assert (ms[0]["charted"], ms[0]["chart_id"]) == (True, "MID-1")
    assert (ms[1]["charted"], ms[1]["chart_id"]) == (False, None)


def test_annotate_flags_a_chart_filed_in_the_other_order():
    """The draw orders a meeting by bracket slot, the chart by whoever filed it.

    They disagree about half the time (48 of the 121 matches the live feed currently
    carries), and everything in the per-match sidecar — the win-probability curve, both
    box-score sides, the serve placement — is written from the chart's player1 forward.
    Unflagged, the panel lays a match's numbers against the wrong two names and draws the
    curve upside down, which is wrong in a way that still looks like a plausible match.
    """
    charted = {("M", 2026, "wimbledon", frozenset(("a one", "b two"))): ("MID-1", "b two")}
    t = _tour("188-2026", "M", _final("A One", "B Two"))
    t["completed"], t["year"], t["season"] = True, 2026, 2026
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    m = t["rounds"][0]["matches"][0]
    # Same match, found under the unordered pair — but the chart leads with the draw's B.
    assert m["chart_id"] == "MID-1"
    assert m["chart_flip"] is True


def test_annotate_does_not_flag_a_chart_in_draw_order():
    charted = {("M", 2026, "wimbledon", frozenset(("a one", "b two"))): ("MID-1", "a one")}
    t = _tour("188-2026", "M", _final("A One", "B Two"))
    t["completed"], t["year"], t["season"] = True, 2026, 2026
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    assert t["rounds"][0]["matches"][0]["chart_flip"] is False


def test_annotate_no_charting_leaves_null():
    t = _tour("w", "M", _final("A", "B"))
    t["completed"], t["year"], t["season"] = True, 2025, 2025
    build_brackets._annotate(t, {"M": {}, "W": {}}, {})     # nothing charted for this event
    m = t["rounds"][0]["matches"][0]
    assert m["charted"] is None and m["chart_id"] is None   # falls back to per-player shading


def test_recent_slams_orders_newest_started_first():
    # Mid-July 2026: Wimbledon (started late June) is the newest begun slam; the seed walks
    # this order and takes the first that harvests complete, so an in-progress top pick falls
    # through to the one before it.
    order = history.recent_slams(date(2026, 7, 15))
    assert order[0] == ("wimbledon", 2026)
    assert order[1] == ("roland garros", 2026)
    assert ("us open", 2026) not in order          # US Open hasn't started by mid-July
    assert ("us open", 2025) in order


def test_annotate_skips_charting_for_live_draws():
    charted = {("M", 2025, "wimbledon", frozenset(("a one", "b two"))): ("MID-1", "a one")}
    t = _tour("w", "M", [{"rank": 100, "label": "Final", "matches": [_match("m1", "A One", "B Two")]}])
    t["year"] = 2025                                        # but NOT completed
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    assert t["rounds"][0]["matches"][0]["charted"] is None
