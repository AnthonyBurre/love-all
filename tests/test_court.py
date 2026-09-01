"""Tests for the court/ball-path SVG renderer.

Pins the drawing's structural invariants (one segment per stroke, winners land in
the lines, errors break outside them, the zone-to-lane mirroring across the net)
without asserting exact pixel coordinates, which are free to be retuned.
"""

import re

from match_charting_project.shots.notation import parse_point
from match_charting_project.viz.court import (
    _BOTTOM,
    _CONTACT_PAD,
    _HALF,
    _LANE_MID,
    _LEFT,
    _NET,
    _SERVE_STANCE,
    _SERVICE_F,
    _THEME,
    _TOP,
    _bounces_from_shots,
    _contact_points,
    _depth_y,
    _lane_x,
    _opening_contact,
    _serve_origin_x,
    _shots_from_tokens,
    _tip_elems,
    point_rally_svg,
    rally_svg,
)


def _segments(svg: str) -> int:
    """Ball-path segments carry a data-shot index; court lines and the × don't."""
    return svg.count("data-shot=")


def _rings(svg: str) -> "list[tuple[float, float]]":
    """The small rings marking a ball that bounced, as (x, y)."""
    return [(float(x), float(y)) for x, y in
            re.findall(r'<circle cx="(-?[\d.]+)" cy="(-?[\d.]+)" r="1.9"', svg)]


def _segment_ends(svg: str) -> "list[tuple[float, float, float, float]]":
    """Each drawn stroke as (x1, y1, x2, y2), in stroke order."""
    return [tuple(float(v) for v in m) for m in re.findall(
        r'<line data-shot="\d+" x1="(-?[\d.]+)" y1="(-?[\d.]+)" '
        r'x2="(-?[\d.]+)" y2="(-?[\d.]+)"', svg)]


def _contacts(tokens):
    """The bounces, contacts and bounced flags behind a token sequence, built the way
    rally_svg builds them so a test can never be reading a different drawing."""
    shots = _shots_from_tokens(tokens)
    bounces = _bounces_from_shots(shots, True, "deuce")
    start = _opening_contact(shots, "deuce")
    return bounces, *_contact_points(bounces, shots, start)


def _tip_points(el: str) -> "list[tuple[float, float]]":
    """The three points of a wingtip chevron: wing, apex, wing."""
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", el.split('d="')[1].split('"')[0])]
    return list(zip(nums[::2], nums[1::2]))


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


def test_each_segment_carries_direction_wingtips():
    # Two chevrons per stroke, so a zig-zag can't be read backwards. They're the
    # only <path> elements in the drawing, and they point along the segment.
    svg = rally_svg("4f1f3*", server=1)                 # three full-length strokes
    assert svg.count("<path") == 2 * _segments(svg) == 6

    # Cramped segments thin out rather than smear arrowheads on top of each other:
    # one tip when there's room for one, none when there isn't.
    assert len(_tip_elems(75, 100, 75, 88, "")) == 1
    assert len(_tip_elems(75, 100, 75, 96, "")) == 0


def test_wingtips_point_the_way_the_ball_travelled():
    # Each chevron is wing / apex / wing; the apex leads, the wings trail behind.
    for (x1, y1, x2, y2) in [(75, 176, 75, 60), (75, 60, 75, 176), (20, 95, 130, 95)]:
        for (wa, apex, wb) in map(_tip_points, _tip_elems(x1, y1, x2, y2, "")):
            # The apex is further along the travel direction than either wing.
            def along(p):
                return (p[0] - x1) * (x2 - x1) + (p[1] - y1) * (y2 - y1)

            assert along(apex) > along(wa) and along(apex) > along(wb)
            # And it sits on the segment, between the endpoints.
            assert min(x1, x2) <= apex[0] <= max(x1, x2)
            assert min(y1, y2) <= apex[1] <= max(y1, y2)


def test_css_class_mode_uses_site_classes_not_inline_colours():
    css = rally_svg("4f1f3*", server=1, css_classes=True)
    assert "ct-net" in css and "ct-shot" in css and "ct-tip" in css
    assert _THEME["line"] not in css                   # court colour comes from CSS vars


def test_empty_point_still_draws_a_court():
    svg = rally_svg([])
    assert "<svg" in svg and _segments(svg) == 0


# --- contact points: where the stroke was played from, not where the ball landed -------
# A charted point says where each ball went; it never says where the player stood to hit
# the next one. The drawing infers that, and these pin the three rules it infers by.


def test_a_groundstroke_is_struck_past_where_the_ball_bounced():
    """The bounce is where the ball landed; the player meets it a step later, still on
    the ball's line. Drawing the answer as leaving the bounce itself is what made a ball
    down the middle look like a shot struck from the middle of the court."""
    bounces, contacts, _ = _contacts(["svT", "Bd2", "Fd1", "Bd3"])
    for i in (1, 2, 3):
        prev, contact = bounces[i - 1], contacts[i]
        # Same half as the ball it answers, and further from the net than the bounce.
        assert (prev.y < _NET) == (contact[1] < _NET)
        assert abs(contact[1] - _NET) > abs(prev.y - _NET)


def test_a_serve_is_returned_from_the_baseline_not_the_service_box():
    """A serve bounces inside the service box, but nobody returns from there — the
    returner's stance sets where they meet it, not how short the serve landed."""
    bounces, contacts, _ = _contacts(["svT", "Bd2"])
    serve, returner = bounces[0], contacts[1]
    assert serve.y > _depth_y(_SERVICE_F, True)          # the serve landed in the box
    assert returner[1] < _depth_y(_SERVICE_F, True)      # the return was struck behind it
    assert abs(returner[1] - _TOP) < 0.2 * _HALF         # and near their own baseline


def test_a_wide_serve_is_returned_from_the_sideline_not_from_off_the_page():
    """Following a wide serve out to the baseline puts the returner past the edge of the
    drawing. The extension stops at the sideline instead — which costs depth, not the
    ball's line, so the serve still reads as one line with its bounce sitting on it."""
    _, contacts, _ = _contacts(["svW", "Bd2"])
    wide = contacts[1]
    assert wide[0] == _LEFT - _CONTACT_PAD               # stopped at the sideline
    _, straight, _ = _contacts(["svT", "Bd2"])
    assert wide[1] > straight[1][1]                      # and taken earlier for it


def test_a_volleyed_ball_is_never_drawn_bouncing():
    """The ball a volley answers did not reach the ground, so nothing may say it did.
    The incoming line stops where it was intercepted, short of where it was aimed."""
    bounces, contacts, bounced = _contacts(["svT", "Bd2", "Fv1", "Bd3"])
    assert bounced == [True, False, True, True]          # only the volleyed ball
    volley_contact = contacts[2]
    aimed_at = bounces[1]
    # Met in its own half, nearer the net than the bounce it never reached.
    assert (volley_contact[1] < _NET) == (aimed_at.y < _NET)
    assert abs(volley_contact[1] - _NET) < abs(aimed_at.y - _NET)


def test_only_the_balls_that_bounced_get_a_ring():
    """The ring is the charted datum — where the ball actually landed. The last stroke
    ends at its own bounce, so it needs none."""
    assert len(_rings(rally_svg(["svT", "Bd2", "Fd1", "Bd3"]))) == 3    # all but the last
    assert len(_rings(rally_svg(["svT", "Bd2", "Fv1", "Bd3"]))) == 2    # minus the volleyed
    assert len(_rings(rally_svg(["svT", "Bd2"]))) == 1                  # the serve's own


def test_each_ring_sits_on_the_line_that_ran_past_it():
    """A ball travels straight in plan view, so the bounce it made is a point on the
    segment, not a kink beside it. If the two ever part company the ring is a lie."""
    svg = rally_svg(["svW", "Bd2", "Fd1", "Bd3"])
    segments, rings = _segment_ends(svg), _rings(svg)
    for (x1, y1, x2, y2), (rx, ry) in zip(segments, rings):
        t = (ry - y1) / (y2 - y1)
        assert 0 < t < 1                                  # between the two contacts
        assert abs((x1 + t * (x2 - x1)) - rx) < 0.2       # and on the line between them


def test_a_drop_shot_lands_short_and_a_lob_lands_deep():
    """The two shortest and deepest balls in tennis, each drawn where it lands."""
    def landing(tok):
        return _contacts(["svT", tok])[0][1]

    drop, lob, drive = landing("Fp2"), landing("Fl2"), landing("Fd2")
    # All three are the second stroke, so all three land in the same half.
    for b in (drop, lob, drive):
        assert b.y > _NET
    assert drop.y < drive.y < lob.y                    # shortest, ordinary, deepest
    assert drop.y - _NET < 0.25 * _HALF                # a drop shot dies near the net
    assert lob.y - _NET > 0.85 * _HALF                 # a lob lands on the baseline


def test_a_charted_depth_still_beats_the_stroke_kind():
    """The kind is a fallback for the depth the notation usually omits, not an override
    of the depth it recorded."""
    from match_charting_project.shots.notation import parse_point
    from match_charting_project.viz.court import _bounces_from_shots
    # "u" is a forehand drop shot; "9" charts it deep, which is what the ball did.
    shots = parse_point("4b2u29*", None, 1, 1).shots
    charted = _bounces_from_shots(shots, True, "deuce")[2]
    assert abs(charted.y - _NET) > 0.8 * _HALF


def test_the_server_stands_behind_their_own_baseline():
    """A serve struck from inside the court is the one thing in the drawing every viewer
    can check against tennis, so it has to be right. A sequence that opens mid-rally has
    no real origin and is anchored just inside instead, which is what tells them apart."""
    served = _contacts(["svT", "Bd2"])[1][0]
    mid_rally = _contacts(["Fd1", "Bs3"])[1][0]
    assert served[1] == _BOTTOM + _SERVE_STANCE          # behind the baseline
    assert mid_rally[1] < _BOTTOM                        # inside it
    # And behind it by enough to read as behind it, not as a rounding wobble.
    assert served[1] - _BOTTOM > 0.03 * _HALF


def test_a_serve_leaves_a_bounce_in_its_own_service_box():
    """The serve's line runs on to wherever the returner met it, so the spot in the box is
    what makes the first ball read as a serve rather than as one long diagonal."""
    bounces, _, bounced = _contacts(["svW", "Bd2"])
    serve = bounces[0]
    assert bounced[0]                                    # a landed serve bounced
    assert _depth_y(_SERVICE_F, True) < serve.y < _NET   # between service line and net
    assert _LEFT < serve.x < _LANE_MID                   # in the deuce court's own box
    # and it is drawn, because the line runs on past it
    assert any(abs(x - serve.x) < 0.1 and abs(y - serve.y) < 0.1
               for x, y in _rings(rally_svg(["svW", "Bd2"])))
