"""Match win-probability — the score-tree layer on top of the point eval.

Answers "how is the *match* going?" by propagating a single number — each player's
probability of winning a point on their own serve — up the scoring tree:
point -> game -> set -> match. That propagation is exact under the assumption that
points are independent given the server (validated by the ``score_aware_eval``
experiment). Graduated from ``experiments/match_winprob/`` so the Pages-site build
(and the JS port in ``docs/js/winprob.js``) can consume it.

Everything is from **player1's** perspective (``wp`` = P(player1 wins the match)).
Two parameters drive it:

    p1 = P(player1 wins a point when player1 serves)
    p2 = P(player2 wins a point when player2 serves)

For an upcoming matchup those come from each player's career serve+return rates
(``current_strength`` + ``matchup_strength``); for a live/charted match, ``parse_score``
decodes each point's score columns into a ``Score``.

Standard scoring (game to 4 by 2 with deuce; set to 6 by 2; 7-point tiebreak at 6-6;
best-of-3 or -5). Two documented <0.1% approximations: the first server of each new set
is the alternation of the previous set's, and non-standard historical final-set rules
default to the 6-6 tiebreak (``final_tb_games`` overrides for e.g. 2019 Wimbledon 12-12).
"""

from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache

_PT = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4}


@dataclass
class Score:
    """A point's full match-score context, from player1's perspective."""
    sets_a: int       # player1 sets won
    sets_b: int       # player2 sets won
    games_a: int      # player1 games in the current set
    games_b: int      # player2 games in the current set
    pa: int           # player1 points in the current game (or tiebreak)
    pb: int           # player2 points
    p1_serves: bool   # player1 serves the current point
    in_tiebreak: bool = False


@lru_cache(maxsize=None)
def game_wp(g: float, a: int, b: int) -> float:
    """P(server wins the game) from server/returner point counts (a, b)."""
    if a >= 4 and a - b >= 2:
        return 1.0
    if b >= 4 and b - a >= 2:
        return 0.0
    if a >= 3 and b >= 3:
        d = g * g / (g * g + (1 - g) * (1 - g))
        if a == b:
            return d                 # deuce
        return g + (1 - g) * d if a > b else g * d   # AD server / AD returner
    return g * game_wp(g, a + 1, b) + (1 - g) * game_wp(g, a, b + 1)


class MatchWP:
    """P(player1 wins) over the full score tree, given each player's serve strength."""

    def __init__(self, p1: float, p2: float, best_of: int = 3,
                 final_tb_games: int = 6, final_tb_target: int = 7):
        self.p1, self.p2 = p1, p2
        self.sets_to_win = best_of // 2 + 1
        self.final_tb_games = final_tb_games
        self.final_tb_target = final_tb_target
        self.hold1 = game_wp(p1, 0, 0)
        self.hold2 = game_wp(p2, 0, 0)
        self._set: dict = {}
        self._tb: dict = {}
        self._match: dict = {}

    # -- tiebreak ----------------------------------------------------------
    @staticmethod
    def _tb_server_is_starter(points_played: int) -> bool:
        return ((points_played + 1) // 2) % 2 == 0

    def tb_win(self, a: int, b: int, starter1: bool, target: int = 7) -> float:
        """P(player1 wins a tiebreak) from points (a, b); ``starter1`` served point 1."""
        if a >= target and a - b >= 2:
            return 1.0
        if b >= target and b - a >= 2:
            return 0.0
        if a == b and a >= target - 1:
            al, be = self.p1, 1 - self.p2
            return al * be / (al * be + (1 - al) * (1 - be))
        key = (a, b, starter1, target)
        if key in self._tb:
            return self._tb[key]
        server1 = starter1 == self._tb_server_is_starter(a + b)
        pa = self.p1 if server1 else (1 - self.p2)
        v = pa * self.tb_win(a + 1, b, starter1, target) + \
            (1 - pa) * self.tb_win(a, b + 1, starter1, target)
        self._tb[key] = v
        return v

    # -- set ---------------------------------------------------------------
    def set_win(self, ga: int, gb: int, p1_serves: bool, final: bool = False) -> float:
        """P(player1 wins the set) from the start of a game at games (ga, gb)."""
        if ga >= 6 and ga - gb >= 2:
            return 1.0
        if gb >= 6 and gb - ga >= 2:
            return 0.0
        tb_games = self.final_tb_games if final else 6
        if ga >= tb_games and gb >= tb_games:
            target = self.final_tb_target if final else 7
            return self.tb_win(0, 0, p1_serves, target)
        key = (ga, gb, p1_serves, final)
        if key in self._set:
            return self._set[key]
        gw = self.hold1 if p1_serves else (1 - self.hold2)
        v = gw * self.set_win(ga + 1, gb, not p1_serves, final) + \
            (1 - gw) * self.set_win(ga, gb + 1, not p1_serves, final)
        self._set[key] = v
        return v

    # -- match -------------------------------------------------------------
    def match_win(self, sa: int, sb: int, p1_serves_first: bool) -> float:
        """P(player1 wins the match) from completed sets (sa, sb), next set at 0-0."""
        if sa >= self.sets_to_win:
            return 1.0
        if sb >= self.sets_to_win:
            return 0.0
        key = (sa, sb, p1_serves_first)
        if key in self._match:
            return self._match[key]
        final = (sa == self.sets_to_win - 1 and sb == self.sets_to_win - 1)
        ps = self.set_win(0, 0, p1_serves_first, final)
        v = ps * self.match_win(sa + 1, sb, not p1_serves_first) + \
            (1 - ps) * self.match_win(sa, sb + 1, not p1_serves_first)
        self._match[key] = v
        return v

    def pre_match(self) -> float:
        """P(player1 wins) at 0-0, averaged over who serves first (~symmetric)."""
        return 0.5 * (self.match_win(0, 0, True) + self.match_win(0, 0, False))

    # -- live state composition -------------------------------------------
    def _is_final_set(self, s: Score) -> bool:
        return s.sets_a == self.sets_to_win - 1 and s.sets_b == self.sets_to_win - 1

    def _next_set_server(self, s: Score) -> bool:
        if s.in_tiebreak:
            first = self._tb_starter1(s)
        else:
            first = s.p1_serves if (s.games_a + s.games_b) % 2 == 0 else (not s.p1_serves)
        return not first

    def _tb_starter1(self, s: Score) -> bool:
        server1_now = s.p1_serves
        return server1_now if self._tb_server_is_starter(s.pa + s.pb) else (not server1_now)

    def _game_wp(self, s: Score, pa: int, pb: int, starter1: bool, target: int) -> float:
        if s.in_tiebreak:
            return self.tb_win(pa, pb, starter1, target)
        if s.p1_serves:
            return game_wp(self.p1, pa, pb)
        return 1 - game_wp(self.p2, pb, pa)

    def _compose(self, pgw: float, s: Score, final: bool, nss: bool) -> float:
        if s.in_tiebreak:
            pset = pgw
        else:
            pset = pgw * self.set_win(s.games_a + 1, s.games_b, not s.p1_serves, final) + \
                (1 - pgw) * self.set_win(s.games_a, s.games_b + 1, not s.p1_serves, final)
        return pset * self.match_win(s.sets_a + 1, s.sets_b, nss) + \
            (1 - pset) * self.match_win(s.sets_a, s.sets_b + 1, nss)

    def wp(self, s: Score) -> float:
        """Live P(player1 wins the match) at the point with score ``s``."""
        final = self._is_final_set(s)
        target = self.final_tb_target if final else 7
        starter1 = self._tb_starter1(s) if s.in_tiebreak else False
        pgw = self._game_wp(s, s.pa, s.pb, starter1, target)
        return self._compose(pgw, s, final, self._next_set_server(s))

    def leverage(self, s: Score) -> float:
        """How much this point swings the match: WP(player1 wins it) − WP(loses it)."""
        final = self._is_final_set(s)
        target = self.final_tb_target if final else 7
        starter1 = self._tb_starter1(s) if s.in_tiebreak else False
        nss = self._next_set_server(s)
        win = self._compose(self._game_wp(s, s.pa + 1, s.pb, starter1, target), s, final, nss)
        lose = self._compose(self._game_wp(s, s.pa, s.pb + 1, starter1, target), s, final, nss)
        return win - lose


# -- serve+return strength inputs -----------------------------------------

def parse_score(svr, set1, set2, gm1, gm2, pts, tb_games: int = 6) -> "Score | None":
    """Decode one point's score columns into a player1-perspective ``Score``."""
    if not pts or "-" not in pts or None in (svr, set1, set2, gm1, gm2):
        return None
    toks = pts.split("-")
    if len(toks) != 2:
        return None
    tb = any(t not in _PT for t in toks)
    if not tb and toks == ["0", "0"] and gm1 == gm2 == tb_games and gm1 >= 6:
        tb = True
    try:
        sp, rp = (int(toks[0]), int(toks[1])) if tb else (_PT[toks[0]], _PT[toks[1]])
    except (ValueError, KeyError):
        return None
    pa, pb = (sp, rp) if svr == 1 else (rp, sp)
    return Score(int(set1), int(set2), int(gm1), int(gm2), pa, pb, svr == 1, tb)


def league_mu(con) -> dict:
    """``gender -> mean serve-points-won`` (the additive strength model's anchor)."""
    rows = con.execute(
        "SELECT m.gender g, count(*) n, "
        "       sum(CASE WHEN p.pt_winner = p.svr THEN 1 ELSE 0 END) w "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) GROUP BY g"
    ).fetchall()
    return {g: w / n for g, n, w in rows}


def matchup_strength(serve_a, return_a, serve_b, return_b, mu,
                     lo: float = 0.30, hi: float = 0.92) -> "tuple[float, float]":
    """Combine two players' serve+return rates into (pA, pB) for a head-to-head.

    ``pA = serve_A − return_B + (1 − mu)`` (an above-average returner drags the
    server's point-win prob down), clamped to a sane band.
    """
    pa = min(hi, max(lo, serve_a - return_b + (1 - mu)))
    pb = min(hi, max(lo, serve_b - return_a + (1 - mu)))
    return pa, pb


def current_strength(con, k: int = 100) -> "tuple[dict, dict]":
    """``(gender, player) -> (serve_rate, return_rate)`` over their whole charted career.

    Each rate shrunk toward the gender mean with pseudo-count ``k`` (so thin-history
    players tend toward an even matchup). Returns ``(strength, mu)``.
    """
    mu = league_mu(con)
    serve = con.execute(
        "SELECT m.gender g, CASE WHEN p.svr=1 THEN m.player1 ELSE m.player2 END player, "
        "       count(*) n, sum(CASE WHEN p.pt_winner=p.svr THEN 1 ELSE 0 END) w "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) GROUP BY g, player"
    ).fetchall()
    ret = con.execute(
        "SELECT m.gender g, CASE WHEN p.svr=1 THEN m.player2 ELSE m.player1 END player, "
        "       count(*) n, sum(CASE WHEN p.pt_winner<>p.svr THEN 1 ELSE 0 END) w "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) GROUP BY g, player"
    ).fetchall()
    sd = {(g, p): (n, w) for g, p, n, w in serve}
    rd = {(g, p): (n, w) for g, p, n, w in ret}
    out = {}
    for key in set(sd) | set(rd):
        g = key[0]
        sn, sw = sd.get(key, (0, 0))
        rn, rw = rd.get(key, (0, 0))
        out[key] = ((sw + k * mu[g]) / (sn + k), (rw + k * (1 - mu[g])) / (rn + k))
    return out, mu


def walk_forward_strength(con, k: int = 100) -> "tuple[dict, dict]":
    """``match_id -> (p1, p2)`` from serve+return rates over *strictly earlier* matches.

    The no-leakage estimate used for honest calibration (a match is scored only from
    matches played before its day). Returns ``(pq, mu)``.
    """
    mu = league_mu(con)
    cnt: dict = defaultdict(lambda: [0, 0, 0, 0])
    pq: dict = {}

    def rates(key, g):
        c = cnt[key]
        return (c[1] + k * mu[g]) / (c[0] + k), (c[3] + k * (1 - mu[g])) / (c[2] + k)

    def flush(day):
        for mid, g, p1n, p2n, _ in day:
            s1, r1 = rates((g, p1n), g)
            s2, r2 = rates((g, p2n), g)
            pq[mid] = matchup_strength(s1, r1, s2, r2, mu[g])
        for _mid, g, p1n, p2n, pts in day:
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
            if cur_day is not None and d != cur_day:
                if match:
                    day.append(match)
                    match = None
                flush(day)
                day = []
            elif match and match[0] != mid:
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
