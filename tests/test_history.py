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


def test_annotate_charted_gate():
    charted = {("M", 2025, "wimbledon", frozenset(("a one", "b two"))): "MID-1"}
    t = _tour("w", "M", [{"rank": 100, "label": "Final", "matches": [
        _match("m1", "A One", "B Two"),        # in the charted set
        _match("m2", "C Three", "D Four"),     # not charted
    ]}])
    t["completed"], t["year"], t["season"] = True, 2025, 2025
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    ms = t["rounds"][0]["matches"]
    assert (ms[0]["charted"], ms[0]["chart_id"]) == (True, "MID-1")
    assert (ms[1]["charted"], ms[1]["chart_id"]) == (False, None)


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
    charted = {("M", 2025, "wimbledon", frozenset(("a one", "b two"))): "MID-1"}
    t = _tour("w", "M", [{"rank": 100, "label": "Final", "matches": [_match("m1", "A One", "B Two")]}])
    t["year"] = 2025                                        # but NOT completed
    build_brackets._annotate(t, {"M": {}, "W": {}}, charted)
    assert t["rounds"][0]["matches"][0]["charted"] is None
