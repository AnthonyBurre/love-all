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

Net shots opt out of all of it. Every one of those words is anchored on where the ball
was struck from, and a volley is cut off in the air wherever the player could reach it,
so its "zone" is where the ball would have landed — a corner they never stood in. They
are named by destination instead.

The consequence that is easy to miss: **a ball met in the middle third has no down
the line.** There is no corner behind it to line up with, so its two options are
crosscourt and inside-out.

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
    # A drop shot keeps the line vocabulary: unlike a volley it is struck off a ball
    # that bounced, so the zone really is where the player stood.
    ("bh", "BH", "drop", "cc", "crosscourt BH drop shot"),
    ("mid", "FH", "drop", "dtl", "inside-out FH drop shot"),
    # A lob takes no line at all, and carries none to name.
    ("bh", "BH", "lob", "", "BH lob"),
    ("mid", "FH", "lob", "", "FH lob"),
    # A net shot names where it went, and nothing about the line it took.
    ("bh", "BH", "net", "cc", "BH net shot to the BH corner"),
    ("bh", "BH", "net", "dtl", "BH net shot to the FH corner"),
    ("bh", "BH", "net", "mid", "BH net shot to the middle"),
    ("mid", "FH", "net", "cc", "FH net shot to the FH corner"),
    ("mid", "FH", "net", "dtl", "FH net shot to the BH corner"),
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
    A volley was never standing in the corner to step round, so it is named by where
    it went."""
    assert cr.resp_name("bh", ("FH", "net", "cc")) == "FH net shot to the BH corner"
    assert cr.resp_name("bh", ("FH", "net", "dtl")) == "FH net shot to the FH corner"


def test_a_net_shot_never_claims_a_line(cr):
    """The whole line vocabulary is a claim about where the player was standing, which
    for a volley is the one thing the zone does not say."""
    lines = ("crosscourt", "down the line", "inside-out", "inside-in", "through the middle")
    for zone in ("fh", "mid", "bh"):
        for wing in ("FH", "BH"):
            for line in ("cc", "dtl", "mid"):
                name = cr.resp_name(zone, (wing, "net", line))
                assert not any(w in name for w in lines), name
                assert " to the " in name


def test_net_shot_destinations_stay_distinguishable(cr):
    """Dropping the line vocabulary must not collapse two different responses onto one
    name — the analysis still counts them apart, so the panel has to print them apart."""
    for zone in ("fh", "mid", "bh"):
        for wing in ("FH", "BH"):
            names = {cr.resp_name(zone, (wing, "net", ln)) for ln in ("cc", "dtl", "mid")}
            assert len(names) == 3, (zone, wing, names)


def test_serve_plus_one_shares_the_namer():
    """Both experiments name the same responses from the same zones, so both read the
    rule from one place and a change to it cannot reach one report and miss the other."""
    sp = _load("serve_plus_one")
    assert sp.resp_name is sp.CR.resp_name


def test_a_lob_is_not_resolved_by_direction(cr):
    """A groundstroke's third is a choice a player repeats, which is what makes it worth
    conditioning on. A lob's is mostly where they happened to be, so it is not read at
    all — one lob per wing, and a name with no line in it."""
    for d_in in ("1", "2", "3"):
        for d_out in ("1", "2", "3"):
            for hand in ("R", "L"):
                assert cr.resp_line(d_in, d_out, hand, "FH", "lob") == ""
                # every other kind still resolves to one of the three
                assert cr.resp_line(d_in, d_out, hand, "FH", "drive") in ("cc", "dtl", "mid")
    assert cr.resp_name("bh", ("FH", "lob", "")) == "FH lob"
    for word in ("crosscourt", "down the line", "inside-out", "inside-in", "the middle"):
        assert word not in cr.resp_name("mid", ("BH", "lob", ""))


def test_a_lob_has_no_third_to_draw():
    """The drawing is handed the codes, not the prose, so it has to be told the lane is
    unknown rather than be given the middle by default."""
    cr = _load("court_response")
    inc, out = cr.physical_codes(("rally", "drive", "bh", ""), ("FH", "lob", ""), "R")
    assert inc == "3" and out == ""
    # a drop shot from the same state still names a third
    assert cr.physical_codes(("rally", "drive", "bh", ""), ("FH", "drop", "cc"), "R")[1] == "3"
