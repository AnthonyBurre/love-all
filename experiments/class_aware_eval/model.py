"""A win-prob eval that optionally conditions on both players' style classes.

The question: does telling the eval *who* is playing (their style archetypes) make
it predict server-win better than the style-blind eval already does? To keep the
comparison fair, this subclasses the existing ``WinProbModel`` and changes exactly
one thing — the state features. With ``use_class=False`` it reproduces the general
eval byte-for-byte; with ``use_class=True`` it inserts the (server_class,
returner_class) pair into the same shrinkage backoff, so a single coherent eval is
used for the whole point (resolving the cross-class-matchup question), and sparse
class pairings fall back to the style-blind estimate.
"""

import csv
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from match_charting_project.shots.notation import parse_point  # noqa: E402
from match_charting_project.shots.winprob import WinProbModel  # noqa: E402

UNKNOWN = "?"  # players below the style-fingerprint threshold


class ClassAwareModel(WinProbModel):
    """``WinProbModel`` + optional (server_class, returner_class) state features."""

    def __init__(self, use_class: bool = True, class_pos: str = "coarse", **kw):
        super().__init__(**kw)
        self.use_class = use_class
        self.class_pos = class_pos  # "coarse" = global conditioner, "fine" = additive

    def _feats(self, point, j) -> tuple:
        base = super()._feats(point, j)  # (sip, ply, to_hit, wing, kind, dir, appr, depth)
        if not self.use_class:
            return base
        cls = (getattr(point, "s_class", UNKNOWN), getattr(point, "r_class", UNKNOWN))
        if self.class_pos == "fine":
            # Most-specific: class only refines the full rally state, so the backoff
            # shrinks it straight back to the style-blind estimate unless a (state x
            # matchup) cell is well-populated. The strictest "does it add anything?".
            return base + cls
        # Coarse: condition the matchup right after (sip, ply, to_hit) -- well
        # populated, but it nests the fine shot features underneath the classes.
        return base[:3] + cls + base[3:]


def load_class_map(csv_path) -> dict:
    """(gender, player) -> class label, from the player_styles cluster CSV."""
    mapping = {}
    with open(csv_path) as fh:
        for row in csv.DictReader(fh):
            mapping[(row["gender"], row["player"])] = str(row["cluster"])
    return mapping


def in_test(match_id: str, test_frac: float = 0.2) -> bool:
    """Deterministic match-level split (no point leakage across train/test)."""
    return (zlib.crc32(match_id.encode()) % 1000) < test_frac * 1000


def load_points(con, gender: str, class_map: dict, sample: "int | None" = None):
    """Parse points and tag each with its server/returner style classes."""
    sql = (
        "SELECT p.match_id, m.player1, m.player2, p.svr, p.first_serve, "
        "       p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    if sample:
        sql += f" USING SAMPLE reservoir({int(sample)} ROWS) REPEATABLE (1)"
    out = []
    for mid, p1, p2, svr, fs, ss, win in con.execute(sql, [gender]).fetchall():
        pt = parse_point(fs, ss, svr, win)
        if not pt.parse_ok or pt.server_won is None:
            continue
        names = {1: p1, 2: p2}
        pt.s_class = class_map.get((gender, names[pt.server]), UNKNOWN)
        pt.r_class = class_map.get((gender, names[pt.returner]), UNKNOWN)
        pt.match_id = mid
        out.append(pt)
    return out
