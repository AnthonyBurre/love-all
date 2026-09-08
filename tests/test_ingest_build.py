"""The order the ingest steps run in, which is load-bearing and invisible in the output.

`build_matches` repairs, then drops out-of-scope rows, then coerces types, then derives the
tier. Each boundary is there for a reason, and moving a step across one produces a build
that still succeeds and still writes a plausible parquet:

* repair before the derived columns, because in a shifted row every field the derivation
  reads holds something else. A tier read off that row is computed from a duration.
* repair before the scope rule, for the same reason read from the other side: the rule
  matches on the tournament name, which in a shifted row is not in the tournament column.
* scope before the derived columns, so nothing is computed over a row about to leave.

These drive the pieces directly rather than through `build_matches`, which reads CSVs off
disk. What they pin is that the pieces still compose in the documented order.
"""

import pandas as pd

from match_charting_project.analysis.tiers import GRAND_SLAM, OTHER, classify_tier
from match_charting_project.ingest import validate
from matchframes import INTACT, SHIFTED
from matchframes import frame as _frame


def _with_gender(df, gender="M"):
    """`build_matches` adds this column from the filename before validation runs."""
    df = df.copy()
    df["gender"] = gender
    return df


def test_the_tier_is_derived_after_the_repair_not_before():
    """The shifted row is a Wimbledon final. Every column the derivation reads holds the
    value of a column to its right, so a tier taken before the repair is read off the match
    duration — and comes out as a real tier, just not this match's."""
    frame = _frame(SHIFTED)
    assert frame.iloc[0]["tournament"] == "1:30:00"
    assert classify_tier(frame.iloc[0]["tournament"], "M") == OTHER

    repaired, rep = validate.repair_matches(frame)
    assert rep["repaired"] == [SHIFTED["match_id"]]
    assert repaired.iloc[0]["tournament"] == "Wimbledon"
    assert classify_tier(repaired.iloc[0]["tournament"], "M") == GRAND_SLAM


def test_the_repair_restores_the_date_the_coercion_then_parses():
    """The date is rebuilt from the match_id, which is the one field still in the right
    place, and it is rebuilt in the `%Y%m%d` form the coercion downstream expects."""
    repaired, _ = validate.repair_matches(_frame(SHIFTED))
    repaired["date"] = pd.to_datetime(repaired["date"], format="%Y%m%d", errors="coerce")
    assert repaired.iloc[0]["date"] == pd.Timestamp("2026-06-01")


def test_the_scope_drop_happens_before_a_tier_is_derived():
    """A 12-and-under series is not a level anyone should read a rate off, so the row leaves
    before the derived columns are computed rather than after."""
    junior = {**INTACT, "match_id": "20260601-M-Nike_Junior_Tour-F-Ann_Alpha-Bea_Beta",
              "tournament": "Nike Junior Tour"}
    frame = _with_gender(_frame(INTACT, junior))

    kept, rep = validate.drop_out_of_scope(frame)
    assert [r["match_id"] for r in rep["out_of_scope"]] == [junior["match_id"]]

    tiers = [classify_tier(t, g) for t, g in zip(kept["tournament"], kept["gender"])]
    assert tiers == [GRAND_SLAM]                 # only the professional match is labelled


def test_repair_runs_before_scope_so_a_rebuilt_row_can_be_judged_on_its_name():
    """A shifted row's `tournament` cell holds something else entirely, so a scope rule run
    first would be reading the wrong column and could never match. After the repair the
    name is back where the rule looks for it."""
    shifted_junior = {**SHIFTED,
                      "match_id": "20260601-M-Nike_Junior_Tour-F-Ann_Alpha-Bea_Beta"}
    frame = _frame(shifted_junior)

    # Scope first: the tournament column still holds a duration, so nothing is dropped.
    untouched, rep = validate.drop_out_of_scope(frame)
    assert len(untouched) == 1 and rep["out_of_scope"] == []

    # The build's order: repair puts the name back, and the rule then sees it.
    repaired, _ = validate.repair_matches(frame)
    assert repaired.iloc[0]["tournament"] == "Nike Junior Tour"
    kept, rep = validate.drop_out_of_scope(repaired)
    assert kept.empty
    assert [r["tournament"] for r in rep["out_of_scope"]] == ["Nike Junior Tour"]
