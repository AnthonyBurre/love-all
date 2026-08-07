"""Tests for the projections that ship to the site's insights DB.

Two projections here have real failure modes, and both fail *quietly* — the build
succeeds and the panel renders, just with the wrong picture.

The serve-placement CSV carries both a career mix and a recency-weighted one under
similar names, so a build that renames one onto the other's column ships duplicate
columns with the wrong values winning; both are plausible percentages, so nothing
looks wrong. These tests pin which number lands in which column, and that the
reliability gate the experiment computes survives the trip.

The pattern projection joins two experiments into one table, and the return family
carries three columns the rally family has no meaning for. Blanks in those columns
make pandas infer a float dtype, which turns serve direction "6" into "6.0" —
matching none of the renderer's cases, so the serve silently vanishes from every
court drawing. These tests pin the codes as text and the two families as disjoint.
"""

import pandas as pd
import pytest

from match_charting_project.site import build_insights

# One player, both sides: career mix deliberately far from the recent mix so a
# mix-up cannot pass. Only the columns _serve_placement reads are included.
ROWS = [
    {"player": "A Player", "gender": "M", "side": "deuce", "serve": "1st", "n": 9000,
     "wide": 0.30, "t": 0.60, "recent_wide": 0.55, "recent_t": 0.35,
     "recent_n_eff": 1200.0, "recent_years": "2024-2026", "reliable": 1,
     "drift_ratio": 2.5},
    {"player": "A Player", "gender": "M", "side": "ad", "serve": "1st", "n": 8000,
     "wide": 0.40, "t": 0.50, "recent_wide": 0.62, "recent_t": 0.28,
     "recent_n_eff": 1100.0, "recent_years": "2024-2026", "reliable": 0,
     "drift_ratio": 2.5},
    # Second serves and rows with no recent window are not part of the projection.
    {"player": "A Player", "gender": "M", "side": "deuce", "serve": "2nd", "n": 3000,
     "wide": 0.20, "t": 0.40, "recent_wide": 0.25, "recent_t": 0.45,
     "recent_n_eff": 400.0, "recent_years": "2024-2026", "reliable": 1,
     "drift_ratio": 2.5},
    {"player": "B Player", "gender": "W", "side": "deuce", "serve": "1st", "n": 400,
     "wide": 0.44, "t": 0.46, "recent_wide": None, "recent_t": None,
     "recent_n_eff": None, "recent_years": "", "reliable": None,
     "drift_ratio": None},
]
META = [{"gender": "M", "rule": "decay", "rule_param": 10, "recent_matches": 34,
         "n80_wide": 864, "n80_t": 1175, "n80_pay": 11315, "noise_inflation": 3.74,
         "tour_deuce_wide": 0.4427, "tour_deuce_t": 0.4611,
         "tour_ad_wide": 0.5103, "tour_ad_t": 0.4001}]


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(build_insights, "REPORTS", tmp_path)
    return tmp_path


def _write(reports, rows=ROWS, meta=META):
    pd.DataFrame(rows).to_csv(reports / "serve_tendencies_players.csv", index=False)
    if meta is not None:
        pd.DataFrame(meta).to_csv(reports / "serve_tendencies_meta.csv", index=False)


def test_ships_the_recent_mix_not_the_career_one(reports):
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    deuce = serve[serve.side == "deuce"].iloc[0]
    assert deuce.wide == pytest.approx(0.55)      # recent, not the 0.30 career value
    assert deuce.t == pytest.approx(0.35)
    assert deuce.career_wide == pytest.approx(0.30)
    assert deuce.career_t == pytest.approx(0.60)
    assert deuce.career_n == 9000


def test_no_duplicate_columns(reports):
    """The renaming bug this file exists for: duplicate labels reach DuckDB as
    ``wide`` and ``wide_1``, and the panel reads whichever came first."""
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    assert len(set(serve.columns)) == len(serve.columns)


def test_only_first_serves_with_a_recent_window(reports):
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    assert len(serve) == 2                        # both sides of the 1st-serve rows
    assert set(serve.player) == {"A Player"}      # B Player has no recent window


def test_reliability_gate_survives_as_an_int(reports):
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    by_side = serve.set_index("side")
    assert by_side.loc["deuce", "reliable"] == 1
    assert by_side.loc["ad", "reliable"] == 0
    assert by_side["reliable"].dtype.kind == "i"
    assert by_side["n_eff"].dtype.kind == "i"


def test_meta_rows_are_prefixed_and_numeric(reports):
    _write(reports)
    _serve, meta = build_insights._serve_placement()
    keys = {r["key"]: r["value"] for r in meta}
    assert keys["serve_n80_wide_M"] == 864
    assert keys["serve_tour_ad_t_M"] == pytest.approx(0.4001)
    assert all(isinstance(r["value"], float) for r in meta)


def test_missing_csv_is_not_an_error(reports):
    """The experiment may not have been run; the site drops the section instead."""
    serve, meta = build_insights._serve_placement()
    assert serve is None and meta == []


def test_missing_meta_still_ships_the_table(reports):
    _write(reports, meta=None)
    serve, meta = build_insights._serve_placement()
    assert len(serve) == 2 and meta == []


# --- pattern families ------------------------------------------------------------------
# court_response owns the rally family; serve_plus_one owns the return family and adds
# tier/serve_side/serve_dir to it. Minimal rows: only the columns _patterns reads.
CR_ROWS = [
    {"player": "A Player", "gender": "M", "family": "rally", "state": "drive into the middle",
     "response": "crosscourt FH drive", "state_depth": "", "inc_code": 2, "resp_code": 1,
     "lift": 1.8, "count": 40, "n_state": 300, "evidence": 33.9,
     "win_rate": 0.55, "tour_win_rate": 0.51},
    {"player": "A Player", "gender": "M", "family": "ret", "state": "mid-depth drive return",
     "response": "crosscourt FH drive", "state_depth": "mid-depth", "inc_code": 2, "resp_code": 1,
     "lift": 1.7, "count": 30, "n_state": 200, "evidence": 23.0,
     "win_rate": 0.57, "tour_win_rate": 0.52},
]
SP_ROWS = [
    {"player": "A Player", "gender": "M", "family": "ret", "tier": "full",
     "state": "deuce court, T serve · mid-depth drive return", "response": "crosscourt FH drive",
     "serve_side": "deuce", "serve_dir": 6, "state_depth": "mid-depth",
     "inc_code": 2, "resp_code": 1, "lift": 2.0, "count": 90, "n_state": 400, "evidence": 90.0,
     "win_rate": 0.58, "tour_win_rate": 0.56},
    {"player": "B Player", "gender": "W", "family": "ret", "tier": "pooled",
     "state": "mid-depth drive return", "response": "BH drive down the line",
     "serve_side": "", "serve_dir": "", "state_depth": "mid-depth",
     "inc_code": 3, "resp_code": 3, "lift": 1.5, "count": 20, "n_state": 150, "evidence": 11.7,
     "win_rate": 0.49, "tour_win_rate": 0.47},
]


def _write_patterns(reports, sp=SP_ROWS):
    pd.DataFrame(CR_ROWS).to_csv(reports / "court_response_players.csv", index=False)
    if sp is not None:
        pd.DataFrame(sp).to_csv(reports / "serve_plus_one_players.csv", index=False)


def test_return_family_comes_from_serve_plus_one(reports):
    """Both experiments compute a ret family; only one of them may ship, or the panel
    describes one shot twice under two different conditionings."""
    _write_patterns(reports)
    p = build_insights._patterns()
    ret = p[p.family == "ret"]
    assert len(ret) == 2                                  # serve_plus_one's, not the CSV's 1
    assert set(ret.tier) == {"full", "pooled"}
    assert "mid-depth drive return" == ret[ret.tier == "pooled"].iloc[0].state
    assert len(p[p.family == "rally"]) == 1               # court_response's, untouched


def test_serve_dir_survives_as_text_not_a_float(reports):
    """The quiet one: a blank in the column infers float64, "6" becomes "6.0", and the
    renderer's dir === "6" test fails, so the serve disappears from the drawing."""
    _write_patterns(reports)
    p = build_insights._patterns()
    full = p[p.tier == "full"].iloc[0]
    assert full.serve_dir == "6"
    for col in ("inc_code", "resp_code", "serve_dir", "serve_side", "tier"):
        assert p[col].map(type).eq(str).all(), col


def test_rally_rows_carry_blanks_not_nan(reports):
    """The rally family has no side. Those cells reach the panel as text either way, so
    a NaN would print the string "nan" in a card."""
    _write_patterns(reports)
    rally = build_insights._patterns().query("family == 'rally'").iloc[0]
    assert (rally.tier, rally.serve_side, rally.serve_dir) == ("", "", "")


def test_falls_back_to_court_response_when_serve_plus_one_is_missing(reports):
    """A stale checkout should ship the pooled return rows, not an empty section."""
    _write_patterns(reports, sp=None)
    p = build_insights._patterns()
    ret = p[p.family == "ret"]
    assert len(ret) == 1 and set(ret.tier) == {"pooled"}
    assert (ret.iloc[0].serve_side, ret.iloc[0].serve_dir) == ("", "")
