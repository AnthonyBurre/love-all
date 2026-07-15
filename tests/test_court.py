"""Tests for the court/ball-path SVG renderer.

Pins the drawing's structural invariants (one segment per stroke, winners land in
the lines, errors break outside them, the zone-to-lane mirroring across the net)
without asserting exact pixel coordinates, which are free to be retuned.
"""

from match_charting_project.shots.notation import parse_point
from match_charting_project.viz.court import (
    _LANE_MID,
    _THEME,
    _bounces_from_shots,
    _lane_x,
    _serve_origin_x,
    point_rally_svg,
    rally_svg,
)


def _segments(svg: str) -> int:
    """Ball-path segments carry a data-shot index; court lines and the × don't."""
    return svg.count("data-shot=")


def test_returns_svg_document():
    svg = rally_svg("4f1f3*", server=1)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert 'viewBox="0 0 150' in svg


def test_one_segment_per_stroke():
    for raw, n in [("6*", 1), ("4s27f+3*", 3), ("4f29b2b2s1f1f2b2@", 8)]:
        p = parse_point(raw, None, 1, 1)
        assert _segments(rally_svg(p)) == len(p.shots) == n


def test_winner_lands_in_court_error_breaks_out():
    winner = point_rally_svg("4s27f+3*", None, 2, 2)   # FH winner
    assert _THEME["win"] in winner                     # a landed-winner dot
    assert _THEME["miss"] not in winner                # nothing drawn as a miss

    err = point_rally_svg("4f2d#", None, 1, 1)         # deep forced error
    assert _THEME["miss"] in err                       # the miss × / dashed segment


def test_double_fault_serve_is_drawn_as_a_miss():
    # The faulted serve carries only an error location, no terminal symbol.
    svg = point_rally_svg("4n", "4d", 2, 1)
    assert _THEME["miss"] in svg
    assert _segments(svg) == 1


def test_zone_lane_mirrors_across_the_net():
    # Zone 1 (a righty's FH corner) is screen-left in the far half, screen-right
    # in the near half; zone 2 is centred in both.
    assert _lane_x("1", target_top=True) < _lane_x("3", target_top=True)
    assert _lane_x("1", target_top=False) > _lane_x("3", target_top=False)
    assert _lane_x("2", target_top=True) == _lane_x("2", target_top=False)


def test_serve_crosses_diagonally_and_court_mirrors():
    shots = parse_point("6*", None, 1, 1).shots            # ace down the T
    deuce = _bounces_from_shots(shots, True, "deuce")[0]
    ad = _bounces_from_shots(shots, True, "ad")[0]
    # Deuce serve lands in the left box, ad in the right; they mirror about centre.
    assert deuce.x < _LANE_MID < ad.x
    assert round(deuce.x + ad.x, 3) == 2 * _LANE_MID
    # And the serve is a genuine diagonal: origin is on the far side from the box.
    assert _serve_origin_x("deuce") > _LANE_MID     # server right of centre
    assert _serve_origin_x("ad") < _LANE_MID


def test_pts_derives_serve_court():
    # An ad-court score (30-40 -> ad) must place the serve like serve_court="ad",
    # and a deuce-court score (0-0) like serve_court="deuce".
    ace_top = ("6*", None, 1, 1)                       # ace down the T
    ad_from_pts = point_rally_svg(*ace_top, pts="30-40")
    ad_direct = point_rally_svg(*ace_top, serve_court="ad")
    deuce_from_pts = point_rally_svg(*ace_top, pts="0-0")
    deuce_direct = point_rally_svg(*ace_top, serve_court="deuce")
    assert ad_from_pts == ad_direct
    assert deuce_from_pts == deuce_direct
    assert ad_from_pts != deuce_from_pts               # the two sides really differ
    # An unparseable score leaves the explicit serve_court untouched.
    assert point_rally_svg(*ace_top, pts="junk", serve_court="ad") == ad_direct


def test_accepts_raw_string_shots_and_tokens_alike():
    p = parse_point("4f1f3*", None, 1, 1)
    from_str = rally_svg("4f1f3*", server=1)
    from_point = rally_svg(p)
    from_shots = rally_svg(p.shots)
    assert from_str == from_point == from_shots
    assert _segments(rally_svg(["svW", "Fd1", "Bs3", "Fd1"])) == 4


def test_css_class_mode_uses_site_classes_not_inline_colours():
    css = rally_svg("4f1f3*", server=1, css_classes=True)
    assert "ct-net" in css and "ct-shot" in css
    assert _THEME["line"] not in css                   # court colour comes from CSS vars


def test_empty_point_still_draws_a_court():
    svg = rally_svg([])
    assert "<svg" in svg and _segments(svg) == 0
