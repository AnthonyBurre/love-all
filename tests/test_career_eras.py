"""Tests for the optional player_eras layer.

Unit cases pin the chronological splitter; the integration test (skips without a DB)
checks the materialized mapping is deterministic and structurally sound — eras are
contiguous, non-overlapping year ranges and split eras clear the size floor.
"""

import pytest

from match_charting_project.analysis.career_eras import (
    MIN_ERA, compute_player_eras, era_points, greedy_k)
from match_charting_project.paths import DB_PATH


def _player(counts):
    years = sorted(counts)
    return {"years": years, "cnt": counts, "total": sum(counts.values())}


def test_greedy_k_splits_into_balanced_contiguous_eras():
    P = _player({2010: 1000, 2011: 1000, 2012: 1000, 2013: 1000})
    eras = greedy_k(P, 2)
    assert eras == [[2010, 2011], [2012, 2013]]
    assert era_points(P, eras[0]) == era_points(P, eras[1]) == 2000


def test_greedy_k_single_year_cannot_split():
    P = _player({2015: 6000})
    assert greedy_k(P, 2) == [[2015]]   # one era — caller treats this as unsplittable


@pytest.mark.skipif(not DB_PATH.exists(), reason="no duckdb database built")
def test_player_eras_deterministic_and_well_formed():
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    a = compute_player_eras(con)
    b = compute_player_eras(con)
    con.close()

    assert a.equals(b)                                   # seeded per player -> reproducible
    assert {"player", "gender", "era", "year_start", "year_end", "evolved"} <= set(a.columns)

    for (_player, _g), grp in a.groupby(["player", "gender"]):
        grp = grp.sort_values("era")
        assert list(grp["era"]) == list(range(len(grp)))             # eras 0..n-1
        starts, ends = grp["year_start"].tolist(), grp["year_end"].tolist()
        for i in range(1, len(grp)):
            assert starts[i] > ends[i - 1]                           # contiguous, disjoint
        if len(grp) > 1:                                             # a split career
            assert grp["evolved"].all()
            assert (grp["n_eras"] == len(grp)).all()
            assert (grp["n_points"] >= MIN_ERA).all()                # both eras usable
