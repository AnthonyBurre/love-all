"""The out-of-scope rule: what it drops, what it deliberately keeps, and that it says so."""

import pandas as pd

from match_charting_project.ingest import validate


def _matches(*tournaments: str) -> pd.DataFrame:
    return pd.DataFrame({
        "match_id": [f"m{i}" for i in range(len(tournaments))],
        "tournament": list(tournaments),
        "player1": ["A"] * len(tournaments),
        "player2": ["B"] * len(tournaments),
    })


def test_drops_the_under_12_series():
    df, rep = validate.drop_out_of_scope(_matches("Nike Junior Tour", "US Open"))
    assert list(df["tournament"]) == ["US Open"]
    assert [r["match_id"] for r in rep["out_of_scope"]] == ["m0"]


def test_keeps_the_18_and_under_slam_events_and_the_ncaa():
    # The rule is the age bracket, not the word "juniors": these are the top of junior
    # tennis and their finalists reach the tour within about a year.
    kept = ("Australian Open Juniors", "Wimbledon Juniors", "Roland Garros Juniors",
            "US Open Juniors", "NCAA Individual Finals")
    df, rep = validate.drop_out_of_scope(_matches(*kept))
    assert len(df) == len(kept)
    assert rep["out_of_scope"] == []


def test_matching_ignores_case_and_padding():
    df, _ = validate.drop_out_of_scope(_matches("  nike JUNIOR tour "))
    assert df.empty


def test_missing_tournament_is_not_swept_up():
    # A null tournament is a damaged row for `repair_matches` to answer for, not a
    # scope decision — this rule only ever removes something it can name.
    df, rep = validate.drop_out_of_scope(_matches(None))
    assert len(df) == 1 and rep["out_of_scope"] == []


def test_report_names_the_match_and_calls_it_a_scope_finding():
    rep = {"out_of_scope": [{"match_id": "m0", "tournament": "Nike Junior Tour"}],
           "out_of_scope_points": 123, "shifted_rows": 0}
    md = validate.render_markdown({"total_matches": 1, "invalid_surface": 0,
                                   "invalid_surface_values": {}, "unparseable_date": 0,
                                   "duplicate_match_ids": 0, "missing_match_id": 0},
                                  {"total_points": 1, "missing_match_id": 0,
                                   "missing_pt_winner": 0, "duplicate_match_pt": 0,
                                   "empty_first_serve": 0}, rep, None)
    assert "## Out of scope" in md
    assert "m0" in md and "123" in md
    assert "Not a quality finding" in md
