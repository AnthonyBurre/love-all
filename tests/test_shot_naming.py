"""Tests for the plain-language names given to a rally response.

The name of a shot is not a property of the line it travelled. The same line is
crosscourt or inside-out, down the line or inside-in, depending on where the ball
was met and which wing met it — so ``resp_name`` needs the incoming zone as well
as the response. Against the charting project's own definitions:

    crosscourt      from the middle or a far corner, to the opposite far corner
    down the line   starting in a corner, ending in that same corner
    inside-out      from the middle or a corner, against the crosscourt lane
    inside-in       a run-around hit down the line
    down the middle to the middle third

The consequence that is easy to miss, and was: **a ball met in the middle third
has no down the line.** There is no corner behind it to line up with, so its two
options are crosscourt and inside-out. That case is pinned here because it was
mislabelled "down the line" across 459 shipped patterns, in both the site copy and
the reports, with nothing to catch it.

The rule lives in the court_response experiment and is imported by serve_plus_one.
Loaded the way that experiment loads it — the file is a script, not a package.
"""

import importlib.util
from pathlib import Path

import pytest

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_run", EXPERIMENTS / name / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def cr():
    return _load("court_response")


# (zone the incoming ball landed in, wing, stroke kind, line) -> the name
NAMES = [
    # A ball met in a corner, answered off the natural wing: the plain pair.
    ("fh", "FH", "drive", "cc", "crosscourt FH drive"),
    ("fh", "FH", "drive", "dtl", "FH drive down the line"),
    ("bh", "BH", "drive", "cc", "crosscourt BH drive"),
    ("bh", "BH", "drive", "dtl", "BH drive down the line"),
    # A ball met in a corner, run around to use the other wing: the run-around pair.
    ("bh", "FH", "drive", "cc", "inside-out FH drive"),
    ("bh", "FH", "drive", "dtl", "inside-in FH drive"),
    ("fh", "BH", "slice", "cc", "inside-out BH slice"),
    ("fh", "BH", "slice", "dtl", "inside-in BH slice"),
    # A ball met in the middle: crosscourt, or against it — never down the line.
    ("mid", "FH", "drive", "cc", "crosscourt FH drive"),
    ("mid", "FH", "drive", "dtl", "inside-out FH drive"),
    ("mid", "BH", "drive", "cc", "crosscourt BH drive"),
    ("mid", "BH", "drive", "dtl", "inside-out BH drive"),
    # Down the middle, from anywhere, is just that.
    ("mid", "FH", "drive", "mid", "FH drive through the middle"),
    ("bh", "FH", "drive", "mid", "FH drive through the middle"),
]


@pytest.mark.parametrize("zone,wing,kind,line,expected", NAMES)
def test_response_names(cr, zone, wing, kind, line, expected):
    assert cr.resp_name(zone, (wing, kind, line)) == expected


def test_a_ball_met_in_the_middle_never_goes_down_the_line(cr):
    """The invariant behind the mid-court cases above, over the whole vocabulary."""
    for wing in ("FH", "BH"):
        for kind in ("drive", "slice", "net", "other"):
            for line in ("cc", "dtl", "mid"):
                assert "down the line" not in cr.resp_name("mid", (wing, kind, line))


def test_down_the_line_only_ever_starts_in_a_corner(cr):
    """The same invariant read the other way: every name that says down the line
    describes a ball met in a corner and returned to the corner facing it."""
    for zone in ("fh", "mid", "bh"):
        for wing in ("FH", "BH"):
            for kind in ("drive", "slice", "net", "other"):
                for line in ("cc", "dtl", "mid"):
                    name = cr.resp_name(zone, (wing, kind, line))
                    if "down the line" in name:
                        assert zone in ("fh", "bh") and line == "dtl"


def test_run_around_names_need_a_groundstroke(cr):
    """Inside-out and inside-in describe stepping round a ball to hit a groundstroke.
    A volley is taken wherever it was reachable, so it keeps the plain pair."""
    assert cr.resp_name("bh", ("FH", "net", "cc")) == "crosscourt FH net shot"
    assert cr.resp_name("bh", ("FH", "net", "dtl")) == "FH net shot down the line"


def test_serve_plus_one_shares_the_namer():
    """The two experiments named the same responses from two copies of this function,
    and the copies drifted wrong together. serve_plus_one borrows it now, so a
    correction to the rule cannot land on one report and miss the other."""
    sp = _load("serve_plus_one")
    assert sp.resp_name is sp.CR.resp_name
