"""Keeps the two ball-path renderers on the same geometry.

`viz/court.py` renders for the reports; `docs/js/court.js` draws the same picture in the
browser. Drift doesn't crash anything: both keep drawing courts, and the same pattern means
different things in the report and on the site. Only geometry is compared; presentation
(arrowheads, tinted half, cropped frame) is meant to differ. A Python test, so it runs in the
existing pytest job.
"""

import re

import pytest

from match_charting_project.paths import PROJECT_ROOT
from match_charting_project.viz import court

COURT_JS = PROJECT_ROOT / "docs" / "js" / "court.js"

# Each row is (the JS name, the Python value it must equal). The names differ only by the
# leading underscore the Python module uses for its privates.
SHARED = [
    ("LEFT", court._LEFT),
    ("RIGHT", court._RIGHT),
    ("TOP", court._TOP),
    ("BOTTOM", court._BOTTOM),
    ("NET", court._NET),
    ("SERVICE_F", court._SERVICE_F),
    ("LANE_L", court._LANE_L),
    ("LANE_MID", court._LANE_MID),
    ("LANE_R", court._LANE_R),
    ("DEPTH_DEFAULT", court._DEPTH_DEFAULT),
    ("SERVE_DEPTH_F", court._SERVE_DEPTH_F),
    ("STEP_F", court._STEP_F),
    ("NET_CONTACT_F", court._NET_CONTACT_F),
    ("CONTACT_PAD", court._CONTACT_PAD),
    ("SERVE_STANCE", court._SERVE_STANCE),
]


@pytest.fixture(scope="module")
def js() -> str:
    return COURT_JS.read_text()


def _const(js: str, name: str) -> float:
    """Read `const NAME = <number>` out of the JS source, wherever it sits in a run of
    comma-separated declarations."""
    m = re.search(rf"\b{name}\s*=\s*(-?\d+(?:\.\d+)?)", js)
    assert m, f"{name} is no longer declared in court.js"
    return float(m.group(1))


@pytest.mark.parametrize("name,expected", SHARED, ids=[n for n, _ in SHARED])
def test_the_shared_geometry_matches_the_python_renderer(js, name, expected):
    assert _const(js, name) == pytest.approx(expected), (
        f"court.js {name} has drifted from viz/court.py"
    )


def test_the_two_stroke_kinds_that_carry_their_own_depth_agree():
    """A drop shot and a lob are the two strokes whose whole point is their depth, and a
    stored pattern never carries a charted one for either. Both renderers fall back to the
    same pair of numbers, so a pattern reads the same in a report and on the site."""
    js = COURT_JS.read_text()
    block = re.search(r"KIND_DEPTH\s*=\s*\{([^}]*)\}", js)
    assert block, "KIND_DEPTH is no longer declared in court.js"
    found = {k: float(v) for k, v in re.findall(r"(\w+)\s*:\s*(-?[\d.]+)", block.group(1))}
    assert found == court._KIND_DEPTH


def test_the_half_is_derived_and_not_restated(js):
    """`HALF` is net-to-baseline depth. Written as a literal on either side it would survive
    a change to the baselines and silently scale every depth fraction against a stale half."""
    assert re.search(r"HALF\s*=\s*NET\s*-\s*TOP", js), "court.js should derive HALF"
    assert court._HALF == court._NET - court._TOP


def test_every_shared_constant_is_actually_present_in_both(js):
    """A guard on the guard: a renamed constant would make every regex above match nothing,
    and a parametrized test that silently checks nothing is worse than no test."""
    assert len(SHARED) == 15
    for name, _ in SHARED:
        assert re.search(rf"\b{name}\s*=", js), name
