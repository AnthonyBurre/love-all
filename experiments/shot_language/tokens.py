"""Turn a decoded point into a sequence of shot "words".

A point is a sentence in a small shot alphabet; this defines that alphabet. Each
stroke becomes one token capturing *what shot, hit where*, at a granularity coarse
enough for dense n-gram statistics but fine enough to separate real patterns
(serve+1 forehand, slice approach, inside-out forehand):

    serve        ``svW`` / ``svB`` / ``svT``        (wide / body / down-T)
    rally shot   ``<side><kind><dir>``              e.g. ``Fd1`` = forehand drive to
                 zone 1, ``Bs3`` = backhand slice to zone 3, ``Fv·`` = forehand volley
                 (no charted direction)

``side`` F/B from the charted wing; ``kind`` d/s/v/o = drive / slice / net (volley,
overhead, half-volley) / other; ``dir`` is the charted court zone 1/2/3 (``·`` if
unknown). Directions are left as the codebook's raw zones rather than relabelled
crosscourt/line, which would require handedness the token deliberately avoids.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from match_charting_project.shots.notation import stroke_kind  # noqa: E402

START = "<s>"
END = "<end>"
_SERVE_DIR = {"4": "W", "5": "B", "6": "T"}
_KIND = {"drive": "d", "slice": "s", "net": "v", "other": "o"}


def shot_token(shot) -> str:
    """One token for a parsed stroke."""
    if shot.is_serve:
        return "sv" + _SERVE_DIR.get(shot.direction, "?")
    side = shot.side[0] if shot.side else "?"          # F / B
    kind = _KIND.get(stroke_kind(shot.letter, False), "o")
    return f"{side}{kind}{shot.direction or '·'}"


def point_tokens(point) -> "list[str]":
    """The rally as an ordered token list (serve … last stroke). No padding/END."""
    return [shot_token(s) for s in point.shots]


def pretty(tok: str) -> str:
    """Human-readable form of a token for reports."""
    if tok in (START, END):
        return tok
    if tok.startswith("sv"):
        return {"W": "serve wide", "B": "serve body", "T": "serve T"}.get(tok[2:], "serve ?")
    side = {"F": "FH", "B": "BH", "?": "?"}.get(tok[0], "?")
    kind = {"d": "drive", "s": "slice", "v": "net", "o": "shot"}.get(tok[1], "shot")
    return f"{side} {kind}→{tok[2:]}"
