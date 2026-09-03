"""Tests for the per-match sidecars the panel reads on a charted match.

The failure mode here is quiet in the same way the insights projections are: every
figure below is a plausible percentage whichever way it is derived, so a wrong
denominator ships a panel that renders cleanly and lies.

Three of them have a real chance of going wrong:

- Second serves. The upstream summary table's ``second_in`` column counts second-serve
  *points*, not second serves that landed, so the obvious reading makes every player
  100%. These build from the notation instead, and the test pins that a double fault
  lands outside ``second_in`` while staying inside ``second_pts``.
- Break rate is the one figure read off the *other* player's games. Off its own it
  would print the hold rate's complement, which is a real number about the wrong
  player.
- Point length is averaged over the points a player *won*, which is the whole reason
  the two sides differ; averaged over all points it silently prints one number twice.
"""

import json

import pytest

from match_charting_project.shots.notation import serve_dir
from match_charting_project.site import build_match_details as bmd


def fold(rows):
    """Run the point walk the way _match_payload does, and finish both sides."""
    sides = {1: bmd._blank_side(), 2: bmd._blank_side()}
    games: dict = {}
    for r in rows:
        bmd._fold_point(sides, r, games)
    for n in (1, 2):
        served = sum(1 for svr, _ in games.values() if svr == n)
        held = sum(1 for svr, w in games.values() if svr == n and w == n)
        sides[n]["sv_games"], sides[n]["held"] = served, held
    return {n: bmd._finish_side(sides[n]) for n in (1, 2)}


def row(pt, svr, pts, fs, ss, win, gm1=0, gm2=0):
    """One ``points`` row in the column order _POINTS_SQL selects."""
    return ("m", pt, svr, 0, 0, gm1, gm2, pts, fs, ss, win)


# A held game for player 1: an ace out wide, a double fault, a rally won, two more.
HOLD = [
    row(1, 1, "0-0", "4*", None, 1),
    row(2, 1, "15-0", "6d", "5d", 2),          # first serve missed, second missed = DF
    row(3, 1, "15-15", "5f28f3*", None, 1),
    row(4, 1, "30-15", "4f3b1@", None, 1),
    row(5, 1, "40-15", "6b2f1*", None, 1),
]
# A game player 1 broke: player 2 serves and loses it.
BREAK = [
    row(6, 2, "0-0", "4f3*", None, 1, gm1=1, gm2=0),
    row(7, 2, "0-15", "6f1b3@", None, 1, gm1=1, gm2=0),
    row(8, 2, "0-30", "5b3*", None, 2, gm1=1, gm2=0),
    row(9, 2, "15-30", "4f2f3*", None, 1, gm1=1, gm2=0),
    row(10, 2, "15-40", "6b1@", None, 1, gm1=1, gm2=0),
]


def test_second_serve_points_are_not_second_serves_in():
    """A double fault is a second-serve point that did not land.

    ``second_pts`` counts every point that reached a second delivery; the in-rate the
    panel prints divides by it after removing the faults. Conflating the two is the
    upstream table's own trap — there ``second_in == serve_pts - first_in`` in all
    23,256 rows, which would print every server at 100%.
    """
    s = fold(HOLD)[1]
    assert s["serve_pts"] == 5
    assert s["first_in"] == 4                  # one point went to a second serve
    assert s["second_pts"] == 1
    assert s["dfs"] == 1
    # What matchSide() divides: landed second serves over second-serve points.
    assert (s["second_pts"] - s["dfs"]) / s["second_pts"] == 0.0


def test_ace_and_double_fault_come_off_the_notation():
    s = fold(HOLD)[1]
    assert s["aces"] == 1
    assert s["dfs"] == 1
    assert s["serve_won"] == 4                 # the double fault is the point lost


def test_aces_are_split_by_which_delivery_struck_them():
    """The two cores the serve plot deepens, each on its own column's denominator.

    A second-serve ace counted in with the first serves would draw a core inside a column
    the point never reached, and the split is the whole point of the figure: the first
    delivery is hit to be unreturnable and the second is not.
    """
    # The held game's ace is a first-serve ace; one more point, aced on the second delivery
    # after the first missed.
    rows = HOLD + [row(6, 1, "40-30", "6d", "4*", 1)]
    s = fold(rows)[1]
    assert s["aces"] == 2
    assert (s["aces_first"], s["aces_second"]) == (1, 1)
    # Each sits inside the column it is drawn in: first-serve aces among the first serves
    # that landed, second-serve aces among the second serves that did.
    assert s["aces_first"] <= s["first_in"]
    assert s["aces_second"] <= s["second_pts"] - s["dfs"]


def test_break_rate_reads_the_other_players_games():
    """Games broken over games the opponent served — not one minus their own hold."""
    sides = fold(HOLD + BREAK)
    a, b = sides[1], sides[2]
    assert (a["sv_games"], a["held"]) == (1, 1)
    assert (b["sv_games"], b["held"]) == (1, 0)
    # Player 1 held everything *and* broke everything; a break rate taken off their own
    # games would be 0%, which is the number this guards against.
    assert (b["sv_games"] - b["held"]) / b["sv_games"] == 1.0


def test_point_length_is_averaged_over_points_won():
    """The two sides differ, which the all-points career figure cannot do."""
    rows = [
        row(1, 1, "0-0", "4*", None, 1),               # 1 stroke, won by 1
        row(2, 1, "15-0", "4f3b1f2b3@", None, 2),      # 5 strokes, won by 2
    ]
    s = fold(rows)
    assert s[1]["pts_won"] == 1 and s[1]["len_won"] == 1.0
    assert s[2]["pts_won"] == 1 and s[2]["len_won"] == 5.0
    assert s[1]["len_won"] != s[2]["len_won"]


def test_return_winner_is_the_second_stroke_of_the_point():
    """The return ring's core: won on the return itself, matching the career rule
    (rally_len == 2, a winner, and not the server who hit it)."""
    rows = [
        row(1, 1, "0-0", "4b1*", None, 2),      # serve, then a return winner
        row(2, 1, "0-15", "4f3f1*", None, 1),   # three strokes: not a return winner
    ]
    s = fold(rows)
    assert s[2]["ret_winners"] == 1
    assert s[1]["ret_winners"] == 0


def test_placement_counts_the_first_delivery_landed_or_not():
    """The career mix reads direction off the raw first-serve column whether or not it
    went in, so the match figure has to as well or the two are different measurements
    printed side by side as an anchor and its value."""
    rows = [
        row(1, 1, "0-0", "4*", None, 1),               # deuce court: wide, in
        row(2, 1, "15-0", "6d", "5f3*", 1),            # ad court: T missed, then body
        row(3, 1, "15-15", "6*", None, 1),             # deuce court: T, in
    ]
    s = fold(rows)
    assert s[1]["dirs"]["deuce"] == [1, 0, 1]          # wide, body, T
    # The faulted delivery still counts, on the court it was struck to — the point is
    # filed by where the serve went, not by whether it landed.
    assert s[1]["dirs"]["ad"] == [0, 0, 1]
    assert s[1]["dirs2"]["ad"] == [0, 1, 0]            # the second delivery, separately
    assert s[1]["dirs2"]["deuce"] == [0, 0, 0]


def test_serve_side_alternates_within_the_game():
    """Placement is split by court, and the court comes from the score's parity."""
    rows = [
        row(1, 1, "0-0", "4*", None, 1),        # deuce court
        row(2, 1, "15-0", "4*", None, 1),       # ad court
    ]
    s = fold(rows)
    assert s[1]["dirs"]["deuce"] == [1, 0, 0]
    assert s[1]["dirs"]["ad"] == [1, 0, 0]


@pytest.mark.parametrize("raw,want", [
    ("4f28f3*", "4"), ("6*", "6"), ("5d", "5"),
    ("c4*", "4"),                       # a leading net-cord marker is skipped
    ("0f3*", "0"),                      # target explicitly charted as unknown
    ("f28f3*", ""),                     # a stroke letter: the serve went unrecorded
    ("", ""), (None, ""),
])
def test_serve_dir_reads_the_target(raw, want):
    assert serve_dir(raw) == want


def test_payload_is_json_serializable_and_carries_both_sides():
    meta = {"p1": "A", "p2": "B", "gender": "M", "best_of": 3,
            "charted_by": "someone", "won": 1}
    payload = bmd._match_payload("m", meta, HOLD + BREAK, {}, {"M": 0.63})
    assert payload is not None
    assert payload["p"] == ["A", "B"] and len(payload["s"]) == 2
    curve = payload["wp"]["curve"]
    assert len(curve) == len(HOLD + BREAK)
    assert all(0.0 <= wp <= 1.0 for _, wp, _ in curve)
    # Round-trips: the sidecar is written with json.dumps and read by fetch().
    assert json.loads(json.dumps(payload))["id"] == "m"


def test_a_match_with_no_prior_falls_back_to_the_league_mean():
    """The first charted meeting of two unknown players still gets a curve, anchored on
    the tour rather than on nothing."""
    meta = {"p1": "Nobody", "p2": "Nobody Else", "gender": "M", "best_of": 3,
            "charted_by": None, "won": 2}
    payload = bmd._match_payload("m", meta, HOLD, {}, {"M": 0.63})
    assert payload["wp"]["prior"] == [pytest.approx(0.63), pytest.approx(0.63)]
    # Equal strengths, so an even match however the spread is integrated.
    assert payload["wp"]["pre"] == pytest.approx(0.5, abs=0.01)


def test_the_curve_carries_the_predictive_spread():
    """The tree is evaluated across the spread of strengths the match could be played at,
    not once at the best guess.

    Without it the tree compounds a point probability it treats as exact over a couple of
    hundred points, and the answer runs away: a 0.742 / 0.515 pairing came out at 99.98%
    over five sets, and pairs of comparable players came out in the high nineties on which
    of them had the better charted fortnight. The two numbers below are the same score tree
    on the same inputs, differing only in whether the strengths are held fixed.
    """
    from match_charting_project.winprob_match import MatchWP, blend, predictive_models
    plug_in = MatchWP(0.742, 0.515, 5).pre_match()
    predictive = blend(predictive_models(0.742, 0.515, 5), lambda m: m.pre_match())
    assert plug_in > 0.999                      # the runaway
    assert predictive < 0.99                    # pulled back into a claimable range
    assert predictive > 0.9                     # still a heavy favourite, as it should be
    # The spread only ever moves an answer toward the middle, never past it.
    assert 0.5 < predictive < plug_in


def test_predictive_spread_leaves_an_even_match_even():
    """Symmetric inputs stay symmetric: the integration adds no bias of its own."""
    from match_charting_project.winprob_match import blend, predictive_models
    even = blend(predictive_models(0.64, 0.64, 3), lambda m: m.pre_match())
    assert even == pytest.approx(0.5, abs=1e-6)


def test_shot_mix_counts_every_stroke_but_the_serve():
    """The mix denominator is what the player hit, return included.

    Strokes alternate from the serve, so the first rally letter is the returner's: in
    ``4f3b1@`` the forehand is player 2's return and the backhand error is player 1's.
    Two strokes, one on each side, and the serve on neither.
    """
    s = fold([row(1, 1, "0-0", "4f3b1@", None, 2)])
    assert s[1]["rally_shots"] == 1 and s[2]["rally_shots"] == 1
    assert s[2]["fh_gs"] == 1 and s[2]["bh_gs"] == 0
    assert s[1]["bh_gs"] == 1 and s[1]["fh_gs"] == 0


def test_slice_is_a_groundstroke_and_a_volley_is_not():
    """The two denominators the panel prints have to stay apart: the mix is over every
    stroke, and the wing rates are over drives and slices only."""
    # Serve, a forehand slice (r) returned by player 2, a backhand volley winner (z) from
    # the server.
    s = fold([row(1, 1, "0-0", "4r3z1*", None, 1)])
    a, b = s[1], s[2]
    assert (b["rally_shots"], b["slice_shots"], b["fh_gs"]) == (1, 1, 1)
    assert (a["rally_shots"], a["net_shots"], a["bh_gs"]) == (1, 1, 0)
    # The volley winner belongs to the net game, not to the backhand's winner rate.
    assert a["bh_winners"] == 0


def test_error_rates_count_unforced_errors_only():
    """A forced error is charged to whoever forced it everywhere else on this panel, so
    the wing that was picked on does not wear it here either."""
    forced = fold([row(1, 1, "0-0", "4f3b1#", None, 2)])
    unforced = fold([row(1, 1, "0-0", "4f3b1@", None, 2)])
    assert forced[1]["bh_gs"] == 1 and forced[1]["bh_errs"] == 0
    assert unforced[1]["bh_gs"] == 1 and unforced[1]["bh_errs"] == 1


def test_net_errors_are_read_off_the_net_shot_itself():
    """A missed volley is a net error; a passing shot that beat one is not."""
    # Server volleys (v) into the net, unforced.
    s = fold([row(1, 1, "0-0", "4b3v1@", None, 2)])
    assert s[1]["net_shots"] == 1 and s[1]["net_errs"] == 1
    # The returner's backhand set it up and ends nothing: no error against them.
    assert s[2]["bh_errs"] == 0


def test_shot_mix_survives_a_json_round_trip():
    """The tallies ship as counts and the panel divides them, so they have to be in the
    payload rather than only in the walk."""
    meta = {"p1": "A", "p2": "B", "gender": "M", "best_of": 3,
            "charted_by": None, "won": 1}
    payload = bmd._match_payload("m", meta, HOLD + BREAK, {}, {"M": 0.63})
    side = json.loads(json.dumps(payload))["s"][0]
    for k in ("rally_shots", "slice_shots", "net_shots", "net_errs",
              "fh_gs", "bh_gs", "fh_winners", "fh_errs", "bh_winners", "bh_errs"):
        assert k in side
    assert side["rally_shots"] >= side["fh_gs"] + side["bh_gs"]
