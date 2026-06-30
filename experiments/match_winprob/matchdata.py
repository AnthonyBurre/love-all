"""Turn charted points into the inputs the match-WP model needs.

Two jobs:
  - **matchup strength** — each player's probability of winning a point on serve, the
    model's only free parameter. Estimated from both a player's *serve* rate and the
    opponent's *return* rate (a great returner lowers the server's number), combined
    additively around the league mean. Crucially the estimate is **walk-forward**:
    for a given match it uses only matches played *strictly earlier*, so neither that
    match nor the future leaks in — otherwise the calibration would be circular and
    its "predictive" value fake. The cost is honest: players with little prior
    charted history fall back toward the league mean (an even matchup).
  - **score state** — decode each point's ``set/gm/pts/svr`` columns into the
    model's ``Score`` (player1's perspective). ``pts`` is server-first, so it is
    flipped to player1/player2 by ``svr``; games/sets are already player1/player2.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from winprob_match import Score  # noqa: E402

_PT = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4}


def parse_score(svr, set1, set2, gm1, gm2, pts, tb_games: int = 6) -> "Score | None":
    """Decode one point's score columns into a player1-perspective ``Score``.

    A tiebreak point is identified by its score format — integer counts (a token
    outside the game tokens), e.g. ``5-6``. The one ambiguous case is the breaker's
    opening ``0-0``, which looks like a game; it is resolved by ``tb_games`` (the
    game score at which *this set's* tiebreak fires — 6 normally, but e.g. 12 for a
    2019-21 Wimbledon final set, where 6-6 is still ordinary play)."""
    if not pts or "-" not in pts or None in (svr, set1, set2, gm1, gm2):
        return None
    toks = pts.split("-")
    if len(toks) != 2:
        return None
    tb = any(t not in _PT for t in toks)
    if not tb and toks == ["0", "0"] and gm1 == gm2 == tb_games and gm1 >= 6:
        tb = True   # the breaker's opening point, the only game-looking tiebreak score
    try:
        sp, rp = (int(toks[0]), int(toks[1])) if tb else (_PT[toks[0]], _PT[toks[1]])
    except (ValueError, KeyError):
        return None
    pa, pb = (sp, rp) if svr == 1 else (rp, sp)   # server-first -> player1/player2
    return Score(int(set1), int(set2), int(gm1), int(gm2), pa, pb, svr == 1, tb)


def _league_mu(con) -> dict:
    """``gender -> mean serve-points-won`` (the additive model's anchor)."""
    rows = con.execute(
        "SELECT m.gender g, count(*) n, "
        "       sum(CASE WHEN p.pt_winner = p.svr THEN 1 ELSE 0 END) w "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) GROUP BY g"
    ).fetchall()
    return {g: w / n for g, n, w in rows}


def walk_forward_strength(con, k: int = 100) -> "tuple[dict, dict]":
    """``match_id -> (p1, p2)`` from serve+return rates over *strictly earlier* matches.

    ``p_i`` = P(player i wins a point on their serve) in this matchup, combined
    additively: ``server_serve_rate − returner_return_rate + (1 − league_mean)``
    (so an above-average returner pulls the server's number down). Each rate is
    shrunk toward the league mean with pseudo-count ``k``. Strengths are accumulated
    in date order and a match is scored from the counters *before* its day is folded
    in — no leakage of the match itself or anything later. Returns ``(pq, mu)``.
    """
    mu = _league_mu(con)
    # (gender, player) -> [serve_pts, serve_wins, return_pts, return_wins]
    cnt: dict = defaultdict(lambda: [0, 0, 0, 0])
    pq: dict = {}

    def clamp(p):
        return min(0.92, max(0.30, p))

    def rates(key, g):
        c = cnt[key]
        s = (c[1] + k * mu[g]) / (c[0] + k)
        r = (c[3] + k * (1 - mu[g])) / (c[2] + k)
        return s, r

    def flush(day):
        for mid, g, p1n, p2n, _ in day:            # 1) score from pre-day counters
            s1, r1 = rates((g, p1n), g)
            s2, r2 = rates((g, p2n), g)
            pq[mid] = (clamp(s1 - r2 + (1 - mu[g])), clamp(s2 - r1 + (1 - mu[g])))
        for _mid, g, p1n, p2n, pts in day:          # 2) then fold the day in
            for svr, w in pts:
                srv = (g, p1n) if svr == 1 else (g, p2n)
                ret = (g, p2n) if svr == 1 else (g, p1n)
                won = w == svr
                cnt[srv][0] += 1
                cnt[srv][1] += 1 if won else 0
                cnt[ret][2] += 1
                cnt[ret][3] += 0 if won else 1

    sql = (
        "SELECT m.date d, p.match_id mid, m.gender g, m.player1 p1, m.player2 p2, "
        "       p.svr, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.date IS NOT NULL "
        "ORDER BY m.date, p.match_id, p.pt"
    )
    cur = con.execute(sql)
    day, cur_day, match = [], None, None
    while True:
        batch = cur.fetchmany(200_000)
        if not batch:
            break
        for d, mid, g, p1n, p2n, svr, w in batch:
            if cur_day is not None and d != cur_day:      # date boundary -> flush
                if match:
                    day.append(match)
                    match = None
                flush(day)
                day = []
            elif match and match[0] != mid:               # new match, same day
                day.append(match)
                match = None
            cur_day = d
            if match is None:
                match = (mid, g, p1n, p2n, [])
            match[4].append((svr, w))
    if match:
        day.append(match)
    flush(day)
    return pq, mu


def eventual_winners(con) -> dict:
    """``match_id -> winning player (1 or 2)`` from the last charted point."""
    rows = con.execute(
        "SELECT match_id, last(pt_winner ORDER BY pt) AS winner, "
        "       max(set1) AS s1, max(set2) AS s2 "
        "FROM points WHERE pt_winner IN (1,2) GROUP BY match_id"
    ).fetchall()
    # Trust the last point only when the final set tally looks like a finished match.
    return {mid: winner for mid, winner, s1, s2 in rows if winner in (1, 2)}
