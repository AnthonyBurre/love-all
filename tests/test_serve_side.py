"""Tests for the deuce/ad service-side derivation.

Unit cases pin the parity rule on hand-checked scores (a full game, past deuce,
a tiebreak, advantage-set long games, and malformed input). The integration
test re-derives the side over the whole ``points`` table and checks the
structural invariants the plan calls out — every game/tiebreak opens on the
deuce court, the split is ~50/50 with a slight deuce excess — guarded to skip
when no database is built.
"""

import pytest

from match_charting_project.paths import DB_PATH
from match_charting_project.shots.score import AD, DEUCE, NA, serve_side

# (pts, expected side). Sum of the game-token counts (0/15/30/40/AD -> 0/1/2/3/4)
# or of the integer tiebreak counts; even -> deuce, odd -> ad.
GAME_CASES = [
    ("0-0", DEUCE), ("15-0", AD), ("30-0", DEUCE), ("40-0", AD),   # a hold to love
    ("0-15", AD), ("0-30", DEUCE), ("0-40", AD),                   # a break to love
    ("15-15", DEUCE), ("30-15", AD), ("30-30", DEUCE),
    ("15-40", DEUCE), ("30-40", AD),                               # consecutive BPs alternate
]
PAST_DEUCE_CASES = [
    ("40-40", DEUCE), ("AD-40", AD), ("40-AD", AD),                # deuce court, then ad
]
TIEBREAK_CASES = [
    ("0-0", DEUCE), ("1-0", AD), ("0-1", AD), ("1-1", DEUCE),
    ("6-5", AD), ("6-6", DEUCE), ("7-6", AD), ("10-10", DEUCE),
]
# Advantage-set games still scored 15/30/40 past 6-6: token type (not the game
# count) decides, so these read as ordinary games — the reason the derivation
# does not lean on a "gm >= 6-6 means tiebreak" test.
ADVANTAGE_SET_CASES = [
    ("0-0", DEUCE), ("15-0", AD), ("40-40", DEUCE), ("AD-40", AD),
]
MALFORMED = [None, "", "40", "deuce", "1-2-3", "40-foo", "x-y", "-", "15-"]


@pytest.mark.parametrize("pts,side", GAME_CASES + PAST_DEUCE_CASES + TIEBREAK_CASES
                         + ADVANTAGE_SET_CASES)
def test_side_from_score(pts, side):
    assert serve_side(pts) == side


@pytest.mark.parametrize("pts", MALFORMED)
def test_malformed_is_na(pts):
    assert serve_side(pts) == NA


def test_full_game_alternates_each_point():
    # Walk a game point by point; the side must flip on every point.
    seq = ["0-0", "15-0", "15-15", "30-15", "30-30", "40-30", "40-40", "AD-40"]
    sides = [serve_side(p) for p in seq]
    assert sides[0] == DEUCE
    assert all(a != b for a, b in zip(sides, sides[1:]))


def test_only_pts_needed_no_games_or_tiebreak_flag():
    # The rule takes a single argument; games / tiebreak status are not inputs.
    assert serve_side("30-40") == AD


@pytest.mark.skipif(not DB_PATH.exists(), reason="no duckdb database built")
def test_db_invariants():
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows = con.execute("SELECT pts, count(*) FROM points GROUP BY pts").fetchall()
    con.close()

    counts = {DEUCE: 0, AD: 0, NA: 0}
    for pts, n in rows:
        counts[serve_side(pts)] += n
    total = sum(counts.values())

    # Every score parses in this dataset; no side is derived as NA.
    assert counts[NA] == 0
    # ~50/50 with a slight deuce excess (every game/tiebreak opens on deuce).
    frac_deuce = counts[DEUCE] / total
    assert 0.50 < frac_deuce < 0.55
    assert counts[DEUCE] > counts[AD]

    # Structural side checks the plan calls out.
    assert serve_side("0-0") == DEUCE            # every game/tiebreak opens deuce
    assert serve_side("30-40") == AD             # a break point that is ad-court
    assert serve_side("40-AD") == AD
    assert serve_side("15-40") == DEUCE          # a break point that is deuce-court
