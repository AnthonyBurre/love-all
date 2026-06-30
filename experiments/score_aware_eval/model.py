"""A win-prob eval that optionally conditions on the *match score* (leverage).

The question: does telling the eval *where in the match* a point sits — break
point, game/set lead, tiebreak — make it predict server-win better than the
score-blind eval already does? Or are points ~iid given the rally state and serve
number (the classic Klaassen-Magnus "points are nearly independent" finding)? To
keep the comparison fair this subclasses the existing ``WinProbModel`` and changes
exactly one thing — the state features. With ``use_score=False`` it reproduces the
score-blind eval byte-for-byte; with ``use_score=True`` it folds a compact score
tag into the same shrinkage backoff, so sparse score x rally-state cells fall back
to the score-blind estimate.

Score-column conventions (verified against the data, not assumed):
  - ``pts`` is **server-first** — server-ahead states (40-0, AD-40) dominate their
    mirror for *both* servers, which only holds if the left token is the server's
    score. So pts maps straight to the server's perspective.
  - ``gm1/gm2`` and ``set1/set2`` are player1/player2, so they are flipped to the
    server's perspective via ``svr``.
  - Tiebreak points carry integer counts (1,2,3...) rather than 0/15/30/40 game
    tokens, and sit at games >= 6-6.
"""

import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from match_charting_project.shots.notation import parse_point  # noqa: E402
from match_charting_project.shots.winprob import WinProbModel  # noqa: E402

NA = "na"  # missing / unparseable score
_PT = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4}  # game-token -> count
# Leverage in server-first notation: who is one point from winning the game.
_BREAK = {"0-40", "15-40", "30-40", "40-AD"}  # returner one point from the break
_HOLD = {"40-0", "40-15", "40-30", "AD-40"}   # server one point from the hold


def _is_tiebreak(pts: str, g1, g2) -> bool:
    toks = pts.split("-")
    if any(t not in _PT for t in toks):  # integer tiebreak counts aren't game tokens
        return True
    return g1 is not None and g2 is not None and g1 >= 6 and g2 >= 6


def pressure(pts, g1, g2) -> str:
    """Leverage bucket from the (server-first) game score."""
    if not pts or "-" not in pts:
        return NA
    if _is_tiebreak(pts, g1, g2):
        return "tiebreak"
    if pts in _BREAK:
        return "break_pt"
    if pts in _HOLD:
        return "game_pt"
    if pts == "40-40":
        return "deuce"
    return "normal"


def lead(sg, rg, ss, rs) -> str:
    """Coarse match-position bucket from the server's games + sets margin."""
    if None in (sg, rg, ss, rs):
        return NA
    if ss != rs:
        return "set_ahead" if ss > rs else "set_behind"
    gd = sg - rg
    if gd >= 2:
        return "ahead"
    if gd <= -2:
        return "behind"
    return "even"


class ScoreAwareModel(WinProbModel):
    """``WinProbModel`` + an optional compact match-score tag in the state.

    ``components`` selects which per-point score attributes to fold in (any of
    ``"pressure"``, ``"lead"``). ``score_pos`` controls where they enter the
    backoff: ``"coarse"`` (a global conditioner, right after ``sip, ply, to_hit``)
    or ``"fine"`` (only refining the full rally state, the strictest test).
    """

    def __init__(self, use_score: bool = True, score_pos: str = "coarse",
                 components: tuple = ("pressure",), **kw):
        super().__init__(**kw)
        self.use_score = use_score
        self.score_pos = score_pos
        self.components = components

    def _feats(self, point, j) -> tuple:
        base = super()._feats(point, j)  # (sip, ply, to_hit, wing, kind, dir, appr, depth)
        if not self.use_score:
            return base
        tag = tuple(getattr(point, c, NA) for c in self.components)
        if self.score_pos == "fine":
            return base + tag
        return base[:3] + tag + base[3:]


def in_test(match_id: str, test_frac: float = 0.2) -> bool:
    """Deterministic match-level split (no point leakage across train/test)."""
    return (zlib.crc32(match_id.encode()) % 1000) < test_frac * 1000


def load_points(con, gender: str, sample: "int | None" = None):
    """Parse points and tag each with its server-perspective score context."""
    sql = (
        "SELECT p.match_id, p.svr, p.first_serve, p.second_serve, p.pt_winner, "
        "       p.pts, p.gm1, p.gm2, p.set1, p.set2 "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    if sample:
        sql += f" USING SAMPLE reservoir({int(sample)} ROWS) REPEATABLE (1)"
    out = []
    for mid, svr, fs, ss, win, pts, g1, g2, s1, s2 in con.execute(sql, [gender]).fetchall():
        pt = parse_point(fs, ss, svr, win)
        if not pt.parse_ok or pt.server_won is None:
            continue
        sg, rg = (g1, g2) if svr == 1 else (g2, g1)
        sset, rset = (s1, s2) if svr == 1 else (s2, s1)
        pt.pressure = pressure(pts, g1, g2)
        pt.lead = lead(sg, rg, sset, rset)
        pt.match_id = mid
        out.append(pt)
    return out
