"""Tests for the shot-notation decoder.

Unit cases pin the grammar (who won, outcome type, rally length, ending wing) on
hand-decoded points. The integration test re-aggregates parsed points and checks
them against the project's own ``stats_overview`` totals — the same cross-check
the experiment used, now a guarded test (skips when no database is built).
"""

from collections import defaultdict

import pytest

from match_charting_project.paths import DB_PATH
from match_charting_project.shots.notation import parse_point, stroke_kind

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
    assert stroke_kind("l", False) == "other"
    assert stroke_kind("", True) == "serve"


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
