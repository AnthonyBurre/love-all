"""Double-charted matches: which chart is kept, and what happens to one that cannot be read.

A match charted twice is weighted twice in every career rate, in the coverage counts and in
the ace share — and the matches this happens to are not a random sample, they are famous
ones. So one chart per match goes forward. The failure modes are all silent: every wrong
answer here is a match that still has points, still joins, and still aggregates.

Three passes, and each has a rule that is easy to get plausibly wrong:

1. *Where does the second chart start.* Not "the point number went down" — `pt` is not
   sorted in the source files, and one 1975 semifinal opens 45, 47, 46, 48. That rule fires
   thirteen times inside a single honest chart and found 2,174 double-charted matches where
   there are 14. It is "the match's own opening number came round again".
2. *Which chart to keep.* The most complete, not the most recent: of the four matches whose
   two charts genuinely differ, the second is the shorter abandoned one in two cases.
3. *What to do with two charts that are interleaved rather than appended.* The whole match,
   not the offending rows — the two have drifted out of step, so the point numbers have
   stopped referring to the same points, and cutting only where that is visible leaves a
   chart still silently misaligned, now with holes in it.
"""

import pandas as pd

from match_charting_project.ingest import validate


def _pt(match_id, pt, winner=1, score="0-0"):
    """One points row, in the shape `build_points` hands over: `pt` already numeric."""
    return {"match_id": match_id, "pt": pt, "pt_winner": winner, "pts": score,
            "first_serve": "4*"}


def _chart(match_id, pts, winner=1):
    return [_pt(match_id, p, winner) for p in pts]


def _frame(*rows):
    return pd.DataFrame([r for group in rows for r in group])


def test_a_chart_whose_point_numbers_go_backwards_is_still_one_chart():
    """The regression the restart rule exists for. A charter's rows as entered, not as
    played: 45, 47, 46, 48 is one honest chart, and reading a decrease as a chart boundary
    is what turned 14 double-charted matches into 2,174."""
    out, rep = validate.dedupe_points(_frame(_chart("m1", [45, 47, 46, 48])))
    assert len(out) == 4
    assert rep["double_charted"] == 0
    assert rep["matches"] == []


def test_a_second_chart_is_found_where_the_opening_number_comes_round_again():
    out, rep = validate.dedupe_points(
        _frame(_chart("m1", [1, 2, 3, 4, 5], winner=1),
               _chart("m1", [1, 2, 3, 4, 5], winner=2)))
    assert rep["double_charted"] == 1
    assert rep["matches"] == [{"match_id": "m1", "charts": [5, 5], "kept": 5}]
    assert len(out) == 5


def test_the_opening_number_is_the_matchs_own_and_not_a_constant():
    """Charts do not all start at 1, which is why the comparison is against each match's
    own first row. Anchored on a literal 1, neither of these two charts would be found."""
    out, rep = validate.dedupe_points(
        _frame(_chart("m1", [45, 46, 47], winner=1),
               _chart("m1", [45, 46, 47, 48], winner=2)))
    assert rep["matches"] == [{"match_id": "m1", "charts": [3, 4], "kept": 4}]
    assert list(out["pt"]) == [45, 46, 47, 48]


def test_the_most_complete_chart_is_kept_not_the_most_recent():
    """The second chart is the shorter abandoned one about half the time, so "keep the
    newer" throws away a full chart for a partial."""
    # The long chart second: keeping the newer would be right here by luck.
    out, _ = validate.dedupe_points(
        _frame(_chart("m1", [1, 2, 3], winner=1),
               _chart("m1", [1, 2, 3, 4, 5, 6], winner=2)))
    assert len(out) == 6 and set(out["pt_winner"]) == {2}

    # The long chart first: this is the one that separates the two rules.
    out, _ = validate.dedupe_points(
        _frame(_chart("m1", [1, 2, 3, 4, 5, 6], winner=1),
               _chart("m1", [1, 2, 3], winner=2)))
    assert len(out) == 6 and set(out["pt_winner"]) == {1}


def test_two_charts_of_equal_length_keep_the_first_so_builds_are_stable():
    """Every verbatim re-append is a tie. Breaking it arbitrarily would give the same
    corpus a different answer on the next build."""
    out, _ = validate.dedupe_points(
        _frame(_chart("m1", [1, 2, 3], winner=1),
               _chart("m1", [1, 2, 3], winner=2)))
    assert set(out["pt_winner"]) == {1}


def test_rows_repeating_a_point_number_identically_are_dropped_losslessly():
    """Either copy will do, so no rule is needed and nothing is lost."""
    out, rep = validate.dedupe_points(
        _frame(_chart("m1", [1, 2, 3], winner=1),
               _chart("m1", [1, 2, 3, 3], winner=2)))
    assert rep["exact_duplicates"] == 1
    assert list(out["pt"]) == [1, 2, 3]
    assert rep["excluded_matches"] == []           # nothing disagreed, so nothing is lost


def test_a_match_whose_charts_disagree_is_dropped_whole():
    """Interleaved and drifted out of step: the same point number carries a different score
    and winner in each. Cutting only the rows where that is *visible* leaves the rest
    silently misaligned, now with holes in it — so the whole match's points go."""
    conflicted = [
        _pt("m1", 1),                                        # a stray opening row
        _pt("m1", 1), _pt("m1", 2, 1, "15-0"), _pt("m1", 2, 2, "0-15"),
        _pt("m1", 3, 1, "30-0"), _pt("m1", 3, 2, "0-30"),
    ]
    out, rep = validate.dedupe_points(_frame(conflicted, _chart("m2", [1, 2])))
    assert rep["excluded_matches"] == [
        {"match_id": "m1", "rows": 5, "conflicting_points": 2}]
    assert rep["excluded_rows"] == 5
    # The match's points are gone; the untouched neighbour is not.
    assert set(out["match_id"]) == {"m2"} and len(out) == 2


def test_a_frame_with_nothing_double_charted_passes_through_untouched():
    out, rep = validate.dedupe_points(_frame(_chart("m1", [1, 2, 3]), _chart("m2", [1, 2])))
    assert len(out) == 5
    assert rep == {"double_charted": 0, "matches": []}


def test_what_dedupe_cannot_reach_is_named_in_the_points_report():
    """A match that repeats a point number without ever repeating its *opening* one is not
    a chart boundary this can see, so its rows survive the three passes. That is what
    `points_report` is for: the leftovers are counted and named, which is the short list
    that wants a person rather than another heuristic."""
    frame = _frame([_pt("m1", 1), _pt("m1", 2, 1, "15-0"),
                    _pt("m1", 2, 2, "0-15"), _pt("m1", 3)])
    out, rep = validate.dedupe_points(frame)
    assert rep["double_charted"] == 0 and len(out) == 4      # nothing to key on

    report = validate.points_report(out)
    assert report["duplicate_match_pt"] == 2
    assert report["unresolved_matches"] == ["m1"]
