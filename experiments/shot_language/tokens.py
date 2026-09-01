"""Turn a decoded point into a sequence of shot "words".

A point is a sentence in a small shot alphabet; this defines that alphabet. Each
stroke becomes one token capturing *what shot, hit where*, at a granularity coarse
enough for dense n-gram statistics but fine enough to separate real patterns
(serve+1 forehand, slice approach, inside-out forehand):

    serve        ``svW`` / ``svB`` / ``svT``        (wide / body / down-T)
    rally shot   ``<side><kind><dir>``              e.g. ``Fd1`` = forehand drive to
                 zone 1, ``Bs3`` = backhand slice to zone 3, ``Fv·`` = forehand volley
                 (no charted direction)

``side`` F/B from the charted wing; ``kind`` is one letter — ``d`` drive, ``s`` slice,
``v`` net (volley, overhead, half-volley, swinging volley), ``p`` drop shot, ``l`` lob,
``o`` other (a trick shot, or a stroke the charter did not type); ``dir`` is the charted
court zone 1/2/3 (``·`` if unknown).

Zones are the codebook's raw thirds by default, which name the court by the
right-hander convention (1 = a righty's forehand corner). That convention is fine for
counting where balls land and wrong for describing what shot a player hit — a lefty's
crosscourt forehand lands in zone 3 where a righty's lands in zone 1, so the same
stroke gets two different words depending on which hand held the racket. Pass
``lefties`` to ``point_tokens`` to mirror 1↔3 for left-handed hitters and get tokens
that name the shot rather than the half of the court.

The mirror is opt-in because the raw zones are load-bearing elsewhere: four other
experiments read these tokens, and ``docs/js/court.js`` parses ``pretty()`` output back
into zone digits to draw ball paths, where a mirrored digit would be drawn as a literal
court third. Only ``shot_language`` asks for it — see its run.py for why.
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from match_charting_project.shots.notation import stroke_kind  # noqa: E402

START = "<s>"
END = "<end>"
_SERVE_DIR = {"4": "W", "5": "B", "6": "T"}
_KIND = {"drive": "d", "slice": "s", "net": "v", "drop": "p", "lob": "l", "other": "o"}
# Court thirds, mirrored. The middle is its own mirror; an uncharted direction stays
# uncharted rather than becoming a guess.
MIRROR = {"1": "3", "2": "2", "3": "1"}


def hand_map(con) -> dict:
    """Modal charted hand per player name.

    A handful of rows in the upstream matches CSV are column-shifted, with the hand
    column holding a date or a tie name, so anything that isn't R or L is dropped
    before the vote rather than allowed to win one. A player charted only in those rows
    is absent, and callers treat absence as right-handed — the majority case, and the
    one the raw zones already assume.
    """
    rows = con.execute(
        "SELECT player1, player1_hand FROM matches "
        "UNION ALL SELECT player2, player2_hand FROM matches").fetchall()
    votes = defaultdict(Counter)
    for name, hand in rows:
        h = (hand or "").strip().upper()
        if h in ("R", "L"):
            votes[name][h] += 1
    return {n: v.most_common(1)[0][0] for n, v in votes.items()}


def shot_token(shot, mirror: bool = False) -> str:
    """One token for a parsed stroke; ``mirror`` flips the court thirds 1↔3.

    Serves are never mirrored: wide/body/T are already named relative to the service
    box the server is aiming into, so they mean the same shot in either hand.
    """
    if shot.is_serve:
        return "sv" + _SERVE_DIR.get(shot.direction, "?")
    side = shot.side[0] if shot.side else "?"          # F / B
    kind = _KIND.get(stroke_kind(shot.letter, False), "o")
    d = shot.direction or "·"
    return f"{side}{kind}{MIRROR.get(d, d) if mirror else d}"


def point_tokens(point, lefties=()) -> "list[str]":
    """The rally as an ordered token list (serve … last stroke). No padding/END.

    ``lefties`` is the set of hitter numbers (1 and/or 2) holding the racket in their
    left hand; their strokes get mirrored zones. Empty by default, which reproduces the
    raw-zone tokens every other caller of this module expects.
    """
    return [shot_token(s, s.hitter in lefties) for s in point.shots]


def pretty(tok: str) -> str:
    """Human-readable form of a token for reports."""
    if tok in (START, END):
        return tok
    if tok.startswith("sv"):
        return {"W": "serve wide", "B": "serve body", "T": "serve T"}.get(tok[2:], "serve ?")
    side = {"F": "FH", "B": "BH", "?": "?"}.get(tok[0], "?")
    kind = {"d": "drive", "s": "slice", "v": "net", "p": "drop", "l": "lob",
            "o": "shot"}.get(tok[1], "shot")
    return f"{side} {kind}→{tok[2:]}"
