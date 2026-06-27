"""Shot-level layer: decode the point notation into structured strokes.

The raw point strings (``points.first_serve`` / ``second_serve``) are the repo's
richest, least-tapped asset. This subpackage turns them into structured strokes —
the primitive every shot-level analysis (win-probability, player style, sequence
models) builds on. ``notation`` is the pure decoder; ``build`` materializes the
decoded per-point table.
"""

from match_charting_project.shots.notation import (
    ParsedPoint,
    Shot,
    iter_parsed_points,
    other_player,
    parse_point,
    point_features,
    stroke_kind,
)

__all__ = [
    "ParsedPoint",
    "Shot",
    "iter_parsed_points",
    "other_player",
    "parse_point",
    "point_features",
    "stroke_kind",
]
