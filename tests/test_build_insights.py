"""Tests for the projections that ship to the site's insights DB.

The serve-placement projection is the one with a real failure mode: the source
CSV carries both a career mix and a recency-weighted one under similar names, so
a build that renames one onto the other's column ships duplicate columns with the
wrong values winning — silently, since both are plausible percentages. These
tests pin which number lands in which column, and that the reliability gate the
experiment computes survives the trip.
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
