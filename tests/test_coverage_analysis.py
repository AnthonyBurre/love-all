"""Charted-vs-played coverage: the denominators, and the grid they are drawn on.

Coverage here means charted over *played*, never a raw charted count, so every figure
rests on a denominator that has to be derived. Two are structural and hold without any
external results data: a slam singles main draw is 128 players, so 127 matches, and a
1000-level draw varies in size but always ends R16=8, QF=4, SF=2, F=1.

The failure mode is the usual one on this project — a wrong denominator is still a
percentage. Three specific ways it goes wrong, one test each:

* counting qualifying rounds into a numerator whose denominator is the main draw, which
  puts coverage above 100% for a well-charted event;
* letting the naming drift split one event in two, which halves the per-event denominator
  and doubles the apparent number of draws behind a round;
* dropping a round nobody charted, which reads as a gap in the heatmap rather than as the
  0% it is — and 0% is the finding.

Built on an in-memory DuckDB with a handful of hand-counted matches, the way `_cov_db` in
test_live.py does, so the arithmetic is checkable by eye.
"""

import duckdb
import pytest

from match_charting_project.analysis import coverage
from match_charting_project.analysis.tiers import GRAND_SLAM, MASTERS_1000


def _db(rows):
    """A matches table carrying only the columns these aggregations read.

    `rows` are (year, tournament, gender, round, n) — n matches charted in that round.
    """
    con = duckdb.connect()
    con.execute("CREATE TABLE matches (match_id VARCHAR, year INTEGER, "
                "tournament VARCHAR, gender VARCHAR, round VARCHAR, tier VARCHAR)")
    i = 0
    for year, tournament, gender, round_, n in rows:
        tier = GRAND_SLAM if tournament in coverage.SLAMS else MASTERS_1000
        for _ in range(n):
            i += 1
            con.execute("INSERT INTO matches VALUES (?, ?, ?, ?, ?, ?)",
                        [f"m{i}", year, tournament, gender, round_, tier])
    return con


# --- the event label -------------------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    ("Miami Masters", "Miami"),
    ("Miami", "Miami"),
    ("Indian_Wells", "Indian Wells"),
    ("Indian  Wells  Masters", "Indian Wells"),
    # The Canadian event alternates cities year to year and is one event, not two.
    ("Montreal", "Canada"),
    ("Toronto", "Canada"),
    ("Canada Masters", "Canada"),
])
def test_canon_masters_event(raw, want):
    assert coverage.canon_masters_event(raw) == want


# --- slam coverage ---------------------------------------------------------------------

def test_slam_coverage_is_charted_over_the_full_draw():
    con = _db([(2020, "Wimbledon", "M", "R128", 30),
               (2020, "Wimbledon", "M", "F", 1)])
    row = coverage.slam_coverage(con).iloc[0]
    assert row["charted"] == 31
    assert row["played"] == coverage.SLAM_DRAW_MATCHES == 127
    assert row["coverage_pct"] == pytest.approx(round(100 * 31 / 127, 1))


def test_qualifying_is_outside_the_numerator_the_denominator_describes():
    """127 is the main draw. A qualifying match counted into it is coverage of a draw the
    match was not part of, and a fully charted event would read over 100%."""
    con = _db([(2020, "Wimbledon", "M", "R128", 64),
               (2020, "Wimbledon", "M", "Q1", 50)])
    assert coverage.slam_coverage(con).iloc[0]["charted"] == 64


def test_slam_round_completion_divides_by_the_draws_actually_present():
    """`expected` is the round's size times the number of draws in the data — not a
    constant — so two years of a round hold twice as many matches as one."""
    con = _db([(2020, "Wimbledon", "M", "F", 1), (2021, "Wimbledon", "M", "SF", 1)])
    df = coverage.slam_round_completion(con).set_index("round")
    # Two draws are present, so one charted final of a possible two is half the finals.
    assert df.loc["F", "expected"] == 2 and df.loc["F", "completion_pct"] == 50.0
    # And each draw holds two semifinals, so one charted of four is a quarter.
    assert df.loc["SF", "expected"] == 4 and df.loc["SF", "completion_pct"] == 25.0


def test_a_round_nobody_charted_reads_as_zero_and_not_as_a_gap():
    """The rich-get-charted pattern is the finding, and it only shows if an uncharted
    opening round draws as 0% rather than going missing from the grid."""
    con = _db([(2020, "Wimbledon", "M", "F", 1)])
    grid = coverage.slam_round_coverage(con)
    assert list(grid["round"].astype(str)) == list(coverage.SLAM_MAIN_ROUNDS)
    assert grid.set_index("round").loc["R128", "charted"] == 0
    assert grid.set_index("round").loc["R128", "coverage_pct"] == 0.0
    assert grid.set_index("round").loc["F", "coverage_pct"] == 100.0


def test_coverage_is_capped_at_a_hundred_percent():
    """More charted matches than the structure allows means the data is wrong, not that
    the event is 150% covered — the cap keeps a damaged row from bending a colour scale."""
    con = _db([(2020, "Wimbledon", "M", "F", 4)])       # a draw has one final
    assert coverage.slam_round_coverage(con).set_index("round").loc["F", "coverage_pct"] == 100.0
    con = _db([(2020, "Wimbledon", "M", "R128", 200)])
    assert coverage.slam_coverage(con).iloc[0]["coverage_pct"] == 100.0


# --- 1000-level coverage ---------------------------------------------------------------

def test_masters_coverage_measures_only_the_invariant_late_rounds():
    """Draw sizes vary from 56 to 128, so there is no full-draw denominator. R16 onward is
    the same 15 matches in every one of them."""
    con = _db([(2020, "Miami Masters", "M", "R16", 8),
               (2020, "Miami Masters", "M", "QF", 4)])
    row = coverage.masters_coverage(con).iloc[0]
    assert row["charted"] == 12
    assert row["played_late"] == coverage.MASTERS_LATE_MATCHES == 15
    assert row["coverage_pct"] == 80.0


def test_the_naming_drift_is_folded_before_the_event_is_counted():
    """Montreal and Toronto are the same event in alternating years, and the same year's
    rows arrive with and without the Masters tag. Left unfolded they are three events, so
    every per-event denominator is a third of what it should be."""
    con = _db([(2020, "Montreal", "M", "F", 1),
               (2020, "Canada Masters", "M", "SF", 2),
               (2021, "Toronto", "M", "F", 1)])
    df = coverage.masters_coverage(con)
    assert set(df["event"]) == {"Canada"}
    # 2020's two rows are one event-draw carrying three charted matches.
    assert len(df) == 2
    assert df.set_index("year").loc[2020, "charted"] == 3


def test_a_folded_event_counts_once_in_the_round_denominator():
    """The same fold, read from the other side: `draws` counts distinct (year, event)
    pairs, so leaving Montreal and Toronto apart would double the expected finals."""
    con = _db([(2020, "Montreal", "M", "F", 1), (2020, "Canada Masters", "M", "R16", 8)])
    df = coverage.masters_round_completion(con).set_index("round")
    assert df.loc["F", "expected"] == 1                 # one draw, one final
    assert df.loc["R16", "expected"] == 8


def test_the_two_tiers_do_not_leak_into_each_other():
    con = _db([(2020, "Wimbledon", "M", "F", 1), (2020, "Miami Masters", "M", "F", 1)])
    assert set(coverage.slam_coverage(con)["slam"].dropna()) == {"Wimbledon"}
    assert set(coverage.masters_coverage(con)["event"]) == {"Miami"}


def test_the_genders_carry_their_own_denominators():
    """A round's expected count is per gender, so a season charted on one tour and not the
    other must not read as half-covered on both."""
    con = _db([(2020, "Wimbledon", "M", "F", 1), (2020, "Wimbledon", "W", "F", 1),
               (2021, "Wimbledon", "M", "F", 1)])
    df = coverage.slam_round_completion(con).set_index("gender")
    assert df.loc["M", "expected"] == 2 and df.loc["M", "completion_pct"] == 100.0
    assert df.loc["W", "expected"] == 1 and df.loc["W", "completion_pct"] == 100.0
