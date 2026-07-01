"""Tests for the match win-probability model (score tree + serve+return strength).

Unit cases pin the closed-form game probabilities and the martingale identity that
must hold for any (p1, p2): the live WP equals the point-win-weighted average of the
WP after winning vs losing the next point. The integration test (skips without a DB)
checks career strength + a pre-match probability land in sane bands.
"""

import random

import pytest

from match_charting_project.paths import DB_PATH
from match_charting_project.winprob_match import (
    MatchWP, Score, current_strength, game_wp, matchup_strength)


def test_game_wp_closed_form():
    assert game_wp(0.5, 0, 0) == pytest.approx(0.5)
    assert game_wp(0.6, 0, 0) == pytest.approx(0.736, abs=2e-3)   # ~73.6% hold at 60%
    assert game_wp(0.9, 0, 0) > 0.99
    assert game_wp(0.5, 3, 3) == pytest.approx(0.5)               # deuce, even server


def test_symmetry_and_monotonicity():
    m = MatchWP(0.62, 0.62, best_of=3)
    assert m.wp(Score(0, 0, 0, 0, 0, 0, True)) == pytest.approx(0.5, abs=1e-9)
    lo = m.wp(Score(0, 0, 0, 0, 0, 3, True))   # 0-40 down on serve
    hi = m.wp(Score(0, 0, 0, 0, 3, 0, True))   # 40-0 up on serve
    assert lo < 0.5 < hi


# --- martingale: wp(s) == ppt*wp(after win) + (1-ppt)*wp(after loss) ---

def _advance(m, s, p1_won):
    pa, pb = (s.pa + 1, s.pb) if p1_won else (s.pa, s.pb + 1)
    if s.in_tiebreak:
        tgt = m.final_tb_target if m._is_final_set(s) else 7
        if max(pa, pb) >= tgt and abs(pa - pb) >= 2:
            return _after_set(m, s, pa > pb)
        st = m._tb_starter1(s)
        nxt1 = (st == m._tb_server_is_starter(pa + pb))
        return Score(s.sets_a, s.sets_b, s.games_a, s.games_b, pa, pb, nxt1, True), None
    gw = game_wp(m.p1 if s.p1_serves else m.p2, *((pa, pb) if s.p1_serves else (pb, pa)))
    if gw in (1.0, 0.0):
        p1wg = (gw == 1.0) if s.p1_serves else (gw == 0.0)
        return _after_game(m, s, p1wg)
    return Score(s.sets_a, s.sets_b, s.games_a, s.games_b, pa, pb, s.p1_serves, False), None


def _after_game(m, s, p1wg):
    ga, gb = (s.games_a + 1, s.games_b) if p1wg else (s.games_a, s.games_b + 1)
    final = m._is_final_set(s)
    tbg = m.final_tb_games if final else 6
    if (ga >= 6 and ga - gb >= 2) or (gb >= 6 and gb - ga >= 2):
        return _after_set(m, s, ga > gb)
    if ga == tbg and gb == tbg:
        return Score(s.sets_a, s.sets_b, ga, gb, 0, 0, not s.p1_serves, True), None
    return Score(s.sets_a, s.sets_b, ga, gb, 0, 0, not s.p1_serves, False), None


def _after_set(m, s, p1ws):
    sa, sb = (s.sets_a + 1, s.sets_b) if p1ws else (s.sets_a, s.sets_b + 1)
    if sa >= m.sets_to_win:
        return None, 1.0
    if sb >= m.sets_to_win:
        return None, 0.0
    return Score(sa, sb, 0, 0, 0, 0, m._next_set_server(s), False), None


_GAME_PTS = [(a, b) for a in range(4) for b in range(4)] + [(4, 3), (3, 4)]


def test_martingale_identity():
    rng = random.Random(0)
    for best_of in (3, 5):
        m = MatchWP(0.63, 0.59, best_of=best_of)
        worst = 0.0
        for _ in range(20000):
            intb = rng.random() < 0.2
            sa, sb = rng.randint(0, m.sets_to_win - 1), rng.randint(0, m.sets_to_win - 1)
            if intb:
                ga = gb = 6
                pa, pb = rng.randint(0, 8), rng.randint(0, 8)
                if max(pa, pb) >= 7 and abs(pa - pb) >= 2:
                    continue
            else:
                ga, gb = rng.randint(0, 6), rng.randint(0, 6)
                if (ga >= 6 and ga - gb >= 2) or (gb >= 6 and gb - ga >= 2) or (ga == 6 and gb == 6):
                    continue
                pa, pb = rng.choice(_GAME_PTS)
            s = Score(sa, sb, ga, gb, pa, pb, bool(rng.randint(0, 1)), intb)
            ppt = m.p1 if s.p1_serves else (1 - m.p2)

            def succ_wp(p1w):
                sc, term = _advance(m, s, p1w)
                return term if sc is None else m.wp(sc)

            lhs = m.wp(s)
            rhs = ppt * succ_wp(True) + (1 - ppt) * succ_wp(False)
            worst = max(worst, abs(lhs - rhs))
        assert worst < 1e-9, f"best_of={best_of} martingale error {worst}"


@pytest.mark.skipif(not DB_PATH.exists(), reason="no duckdb database built")
def test_current_strength_and_pre_match():
    import duckdb

    con = duckdb.connect(str(DB_PATH), read_only=True)
    strength, mu = current_strength(con)
    con.close()

    assert 0.60 < mu["M"] < 0.70 and 0.53 < mu["W"] < 0.62      # league serve-win bands
    sd, rd = strength[("M", "Novak Djokovic")]
    assert 0.55 < sd < 0.75 and 0.35 < rd < 0.55                # elite server & returner

    s1, r1 = strength[("M", "Novak Djokovic")]
    s2, r2 = strength[("M", "Roger Federer")]
    p1, p2 = matchup_strength(s1, r1, s2, r2, mu["M"])
    wp = MatchWP(p1, p2, best_of=5).pre_match()
    assert 0.30 < wp < 0.70                                      # a plausible tossup-ish edge
