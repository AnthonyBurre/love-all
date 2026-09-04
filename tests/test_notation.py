"""Tests for the shot-notation decoder.

Unit cases pin the grammar (who won, outcome type, rally length, ending wing) on
hand-decoded points. The integration test re-aggregates parsed points and checks
them against the project's own ``stats_overview`` totals — the same cross-check
the experiment used, now a guarded test (skips when no database is built).
"""

from collections import defaultdict

import pytest

from match_charting_project.paths import DB_PATH
from match_charting_project.shots.notation import (
    aggressive_shot,
    blank_mix,
    fold_shot_mix,
    parse_point,
    stroke_kind,
)

# (first_serve, second_serve, server, pt_winner,
#  outcome, server_won, rally_len, ending_side)
CASES = [
    ("4f2d#", None, 1, 1, "forced_error", True, 2, "FH"),
    ("4f29b2b2s1f1f2b2@", None, 1, 1, "unforced_error", True, 8, "BH"),
    ("4b29f2b1d@", None, 1, 1, "unforced_error", True, 4, "BH"),
    ("6*", None, 1, 1, "ace", True, 1, ""),
    ("4b2n#", None, 2, 2, "forced_error", True, 2, "BH"),
    ("4s27f+3*", None, 2, 2, "winner", True, 3, "FH"),
    ("4n", "4b27f3s2f+1f2n@", 1, 1, "unforced_error", True, 6, "FH"),  # 2nd-serve point
    ("6n", "c6*", 2, 2, "ace", True, 1, ""),                          # fault then ace
    ("4n", "4d", 2, 1, "double_fault", False, 1, ""),                 # double fault
]


@pytest.mark.parametrize("fs,ss,svr,win,outcome,server_won,rally,side", CASES)
def test_decode_cases(fs, ss, svr, win, outcome, server_won, rally, side):
    p = parse_point(fs, ss, svr, win)
    assert p.outcome == outcome
    assert p.server_won is server_won
    assert p.rally_len == rally
    assert p.ending_side == side
    assert p.parse_ok
    # The grammar's own winner must agree with the charted winner.
    assert p.winner_by_notation == win


def test_serve_in_play_selects_second_serve():
    p = parse_point("4n", "4b27f3s2f+1f2n@", 1, 1)
    assert p.serve_in_play == 2  # first serve was a fault; point on the second


def test_stroke_kind():
    assert stroke_kind("f", False) == "drive"
    assert stroke_kind("b", False) == "drive"
    assert stroke_kind("r", False) == "slice"
    assert stroke_kind("s", False) == "slice"
    assert stroke_kind("v", False) == "net"
    assert stroke_kind("l", False) == "lob"
    assert stroke_kind("u", False) == "drop"
    assert stroke_kind("t", False) == "other"
    assert stroke_kind("", True) == "serve"


def test_aggressive_shot_reads_all_three_kinds():
    """Winner, own unforced error, and forcing the reply out all count; rally balls don't.

    The third case is the one worth pinning: the credit goes to the stroke *before*
    the ``#``, never to the player who was forced into the error.
    """
    p = parse_point("4b27f3s2f+1f2n@", "", 1, 1)   # server's last stroke misses (@)
    last = len(p.shots) - 1
    assert aggressive_shot(p.shots, last) == (0, 1, 0)
    assert aggressive_shot(p.shots, last - 1) == (0, 0, 0)   # a rally ball, not aggressive

    p = parse_point("4b27f3f1*", "", 1, 1)                   # server's last stroke wins
    last = len(p.shots) - 1
    assert aggressive_shot(p.shots, last) == (1, 0, 0)

    p = parse_point("4b27f3f1n#", "", 1, 1)                  # returner forced into an error
    last = len(p.shots) - 1
    assert aggressive_shot(p.shots, last) == (0, 0, 0), "the forced error is not the hitter's"
    assert aggressive_shot(p.shots, last - 1) == (0, 0, 1), "it credits the shot that forced it"


def test_aggressive_shot_respects_a_truncated_view():
    """With n_shots clipped, a reply outside the window can't be read as induced."""
    p = parse_point("4b27f3f1n#", "", 1, 1)
    forcing = len(p.shots) - 2
    assert aggressive_shot(p.shots, forcing, len(p.shots)) == (0, 0, 1)
    assert aggressive_shot(p.shots, forcing, forcing + 1) == (0, 0, 0)


def test_empty_point_is_not_ok():
    p = parse_point("", "", 1, 1)
    assert not p.parse_ok
    assert "empty" in p.flags


@pytest.mark.skipif(not DB_PATH.exists(), reason="no duckdb database built")
def test_aggregates_match_stats_overview():
    """Parsed aces/double-faults/unforced totals should match the charted stats."""
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    matches = con.execute(
        "SELECT match_id, player1, player2 FROM matches "
        "WHERE match_id IN (SELECT DISTINCT match_id FROM stats_overview) "
        "USING SAMPLE reservoir(200 ROWS) REPEATABLE (7)"
    ).fetchall()
    ids = [m[0] for m in matches]
    names = {m[0]: {1: m[1], 2: m[2]} for m in matches}
    pts = con.execute(
        "SELECT match_id, svr, first_serve, second_serve, pt_winner "
        "FROM points WHERE match_id IN ?",
        [ids],
    ).fetchall()
    ref = con.execute(
        "SELECT match_id, player, aces, dfs, unforced FROM stats_overview "
        "WHERE set = 'Total' AND match_id IN ?",
        [ids],
    ).fetchall()
    con.close()

    parsed = defaultdict(lambda: defaultdict(int))
    for mid, svr, fs, ss, win in pts:
        p = parse_point(fs, ss, svr, win)
        if not p.parse_ok:
            continue
        if p.outcome == "ace":
            parsed[(mid, p.server)]["aces"] += 1
        elif p.outcome == "double_fault":
            parsed[(mid, p.server)]["dfs"] += 1
        elif p.outcome == "unforced_error" and p.last_hitter:
            parsed[(mid, p.last_hitter)]["unforced"] += 1

    tot = defaultdict(int)
    err = defaultdict(int)
    for mid, player, aces, dfs, unforced in ref:
        num = next((k for k, v in names[mid].items() if v == player), None)
        if num is None:
            continue
        got = parsed.get((mid, num), {})
        # Upstream folds double faults into the unforced total.
        for col, charted, mine in (
            ("aces", int(aces or 0), got.get("aces", 0)),
            ("dfs", int(dfs or 0), got.get("dfs", 0)),
            ("unforced", int(unforced or 0), got.get("unforced", 0) + got.get("dfs", 0)),
        ):
            tot[col] += charted
            err[col] += abs(charted - mine)

    assert err["aces"] / max(tot["aces"], 1) < 0.05
    assert err["dfs"] / max(tot["dfs"], 1) < 0.05
    assert err["unforced"] / max(tot["unforced"], 1) < 0.08


# --- shot-type letters ------------------------------------------------------------------
# Three pairs are easy to read for each other and share their wings with each other, so the
# forehand/backhand checks above pass whichever of the three a letter is taken for. These
# pin the letters themselves, against the charting project's Instructions tab.


def test_the_three_easily_confused_letter_pairs():
    """Quoting the contributor spreadsheet (MatchChart 0.3.2.xlsm, Instructions):

        u = forehand drop shot        y = backhand drop shot
        h = forehand half-volley      i = backhand half-volley
        j = forehand swinging volley  k = backhand swinging volley
    """
    from match_charting_project.shots.notation import BH_LETTERS, FH_LETTERS
    assert FH_LETTERS["u"] == "forehand_dropshot"
    assert BH_LETTERS["y"] == "backhand_dropshot"
    assert FH_LETTERS["h"] == "forehand_halfvolley"
    assert BH_LETTERS["i"] == "backhand_halfvolley"
    assert FH_LETTERS["j"] == "forehand_swinging_volley"
    assert BH_LETTERS["k"] == "backhand_swinging_volley"


def test_every_letter_is_on_one_wing_only():
    """Each letter belongs to exactly one wing, which is what the winner and error splits
    are credited from."""
    from match_charting_project.shots.notation import (
        BH_LETTERS,
        FH_LETTERS,
        OTHER_LETTERS,
        SHOT_LETTERS,
    )
    assert not set(FH_LETTERS) & set(BH_LETTERS)
    assert len(SHOT_LETTERS) == len(FH_LETTERS) + len(BH_LETTERS) + len(OTHER_LETTERS)


def test_every_letter_lands_in_the_group_its_stroke_belongs_to():
    """"net" is the strokes played at the net; the drop shot and the lob get one each,
    being opposites; "other" is trick shots and strokes the charter did not type."""
    assert {stroke_kind(c, False) for c in "vzop"} == {"net"}      # volleys, overheads
    assert {stroke_kind(c, False) for c in "hi"} == {"net"}        # half-volleys
    assert {stroke_kind(c, False) for c in "jk"} == {"net"}        # swinging volleys
    assert {stroke_kind(c, False) for c in "uy"} == {"drop"}
    assert {stroke_kind(c, False) for c in "lm"} == {"lob"}
    assert {stroke_kind(c, False) for c in "fb"} == {"drive"}
    assert {stroke_kind(c, False) for c in "rs"} == {"slice"}
    assert {stroke_kind(c, False) for c in "tq"} == {"other"}
    assert stroke_kind("", True) == "serve"


# --- the shot mix ------------------------------------------------------------------------
# One walk, two builds. The per-match sidecar and the career aggregate print one under the
# other on the panel — a match rate with the career rate beneath it as its anchor — so a
# second copy of "which letters are a groundstroke" would eventually put a disagreement on
# screen as a career trend. These pin the rules the shared walk applies.
def _mix(*points):
    """Fold a few points and hand back both players' tallies."""
    acc = {1: blank_mix(), 2: blank_mix()}
    for fs, svr, win in points:
        p = parse_point(fs, None, svr, win)
        assert p.parse_ok, fs
        fold_shot_mix(p, lambda h: acc[h])
    return acc


def test_the_serve_is_on_neither_wing():
    """Skipped outright: it is not a forehand or a backhand, and counting it would put
    every server's mix denominator a third above every returner's."""
    a = _mix(("4f3b1@", 1, 2))
    assert a[1]["rally_shots"] == 1 and a[2]["rally_shots"] == 1


def test_a_slice_is_a_groundstroke_and_a_volley_is_not():
    a = _mix(("4r3z1*", 1, 1))
    assert (a[2]["slice_shots"], a[2]["fh_gs"]) == (1, 1)
    assert (a[1]["net_shots"], a[1]["bh_gs"], a[1]["bh_winners"]) == (1, 0, 0)
    # The put-away is the net game's, and it is counted — the net carries both ends, so the
    # panel can say what coming forward earns as well as what it costs.
    assert a[1]["net_winners"] == 1


def test_the_net_carries_a_winner_and_an_error():
    a = _mix(("4b3v2*", 1, 1), ("4b3v2@", 1, 2), ("4b3v2#", 1, 2))
    # Three volleys: one winner, one unforced miss, and one the passing shot forced — which
    # is charged to whoever forced it, so it lands in neither.
    assert a[1]["net_shots"] == 3
    assert (a[1]["net_winners"], a[1]["net_errs"]) == (1, 1)


def test_only_unforced_errors_count_against_the_stroke():
    """A forced error is charged to the player who forced it, so the wing that was picked
    on does not wear it."""
    forced = _mix(("4f3b1#", 1, 2))
    unforced = _mix(("4f3b1@", 1, 2))
    assert forced[1]["bh_gs"] == 1 and forced[1]["bh_errs"] == 0
    assert unforced[1]["bh_errs"] == 1


def test_a_net_shot_is_the_stroke_not_the_approach():
    """The panel's notation key calls a volley, overhead, half-volley or swinging volley a
    net shot. An approach struck from the baseline is a groundstroke that happens to be
    marked as one, and it stays in the wing it was hit off."""
    a = _mix(("4b3f1+f3v2*", 1, 1))
    # The server's strokes: an approach forehand (f1+), then a volley winner.
    assert a[1]["net_shots"] == 1
    assert a[1]["fh_gs"] == 1 and a[1]["fh_winners"] == 0


def test_the_two_builds_fold_the_same_point_the_same_way():
    """The sidecar's side tallies and the insights walk are the same eleven numbers, because
    they are the same call — this is what lets a career figure anchor a match one."""
    from match_charting_project.site import build_insights, build_match_details

    row = ("m", 1, 1, 0, 0, 0, 0, "0-0", "4f3b1@", None, 2)
    sides = {1: build_match_details._blank_side(), 2: build_match_details._blank_side()}
    build_match_details._fold_point(sides, row, {})

    career = {1: blank_mix(), 2: blank_mix()}
    p = parse_point("4f3b1@", None, 1, 2)
    fold_shot_mix(p, lambda h: career[h])

    for n in (1, 2):
        for k in career[n]:
            assert sides[n][k] == career[n][k], (n, k)
    # And the columns the career build derives from them are the ten the panel reads.
    assert len(build_insights.MIX_RATES) == 10
