"""Tests for the point win-probability eval (the chess "engine eval" analogue).

Unit cases pin the structural invariants that must hold for *any* fitted model:
the per-position values start at the pre-serve base and end at the realized result,
and the per-shot win-probability deltas telescope to that span. The integration
test fits on a DB sample and checks the empirical base rates land in the expected
band (skips when no database is built).
"""

import pytest

from match_charting_project.paths import DB_PATH
from match_charting_project.shots.notation import parse_point
from match_charting_project.shots.winprob import WinProbModel

# A small spread of decoded points to fit a toy model on.
_STRINGS = [
    ("4f8b3f1f*", None, 1, 1),
    ("4b27f3s2f+1f2n@", None, 1, 2),
    ("5f1b2f3*", None, 2, 2),
    ("4r29b2b2s1f1b2@", None, 2, 1),
    ("6*", None, 1, 1),
    ("4f2d#", None, 1, 1),
    ("4n", "4b37f1f1f3*", 2, 2),
]


def _toy_model():
    pts = [parse_point(fs, ss, svr, win) for fs, ss, svr, win in _STRINGS]
    return WinProbModel().fit(pts), pts


def _scorable(pts):
    return [p for p in pts if p.parse_ok and p.server_won is not None and p.shots]


def test_point_values_endpoints_and_length():
    model, pts = _toy_model()
    for p in _scorable(pts):
        vals = model.point_values(p)
        assert len(vals) == len(p.shots) + 1
        assert vals[0] == pytest.approx(model.base(p.serve_in_play))
        assert vals[-1] == (1.0 if p.server_won else 0.0)
        assert all(0.0 <= v <= 1.0 for v in vals)


def test_shot_wpa_telescopes_to_result():
    """Sum of per-shot server deltas == realized result − pre-serve value."""
    model, pts = _toy_model()
    for p in _scorable(pts):
        vals = model.point_values(p)
        total = sum(s["server_delta"] for s in model.shot_wpa(p))
        assert total == pytest.approx(vals[-1] - vals[0], abs=1e-9)


def test_wpa_sign_follows_role():
    """WPA equals the server delta for the server, and its negation for the returner."""
    model, pts = _toy_model()
    for p in _scorable(pts):
        for s in model.shot_wpa(p):
            expect = s["server_delta"] if s["role"] == "server" else -s["server_delta"]
            assert s["wpa"] == pytest.approx(expect)


@pytest.mark.skipif(not DB_PATH.exists(), reason="no duckdb database built")
def test_base_rate_first_serve_beats_second():
    """Fit on a sample; first-serve points are won more often than second-serve ones."""
    import duckdb

    from match_charting_project.shots.notation import iter_parsed_points

    con = duckdb.connect(str(DB_PATH), read_only=True)
    model = WinProbModel().fit(iter_parsed_points(con, sample=200_000))
    con.close()
    b1, b2 = model.base(1), model.base(2)
    assert 0.55 < b1 < 0.72        # servers win most first-serve points
    assert 0.48 < b2 < b1          # ...and fewer on the second serve
