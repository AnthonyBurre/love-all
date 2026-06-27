"""Decode a single tennis point's shot notation into a structured rally.

This is the foundation for treating a tennis point the way a chess engine treats
a game: a point string (e.g. ``4b37y1r3n#``) is a tokenized, alternating-turn
sequence of strokes ending in a terminal result, structurally just like a PGN
move list. Nothing else in the repo decodes these strings yet; everything
downstream (win-probability eval, per-shot quality) builds on the structures here.

Notation reference (Match Charting Project "Instructions" tab / quick-start guide,
http://www.tennisabstract.com/blog/2015/09/23/the-match-charting-project-quick-start-guide/):

- Serve direction: ``4`` wide, ``5`` body, ``6`` down-the-T (``0`` unknown).
- Shot type letter, then optional direction ``1`` (to a righty's forehand) /
  ``2`` (middle) / ``3`` (to a righty's backhand), then optional return depth
  ``7`` shallow / ``8`` mid / ``9`` deep, then modifiers.
- Point ending attaches to the *last* stroke as descriptors: ``*`` winner,
  ``#`` forced error, ``@`` unforced error; with an error location ``n`` net /
  ``d`` deep / ``w`` wide / ``x`` wide-and-deep. Strokes alternate, starting with
  the server, so the last stroke's hitter is who won (``*``) or lost (``#``/``@``).
- A serve that ends in a bare error location with no terminal symbol is a fault
  (the rally, if any, is recorded in the second-serve column).
"""

from dataclasses import dataclass, field

# Shot-type letters, split by the wing that produces them (forehand vs backhand).
# Used both to name the stroke and to credit forehand/backhand winners & errors.
FH_LETTERS = {
    "f": "forehand", "r": "forehand_slice", "v": "forehand_volley",
    "o": "overhead", "u": "forehand_halfvolley", "l": "forehand_lob",
    "h": "forehand_swinging_volley", "j": "forehand_dropshot",
}
BH_LETTERS = {
    "b": "backhand", "s": "backhand_slice", "z": "backhand_volley",
    "p": "backhand_overhead", "y": "backhand_halfvolley", "m": "backhand_lob",
    "i": "backhand_swinging_volley", "k": "backhand_dropshot",
}
OTHER_LETTERS = {"t": "trick", "q": "unknown_shot"}
SHOT_LETTERS = set(FH_LETTERS) | set(BH_LETTERS) | set(OTHER_LETTERS)

SERVE_DIRS = {"4", "5", "6", "0"}
DIRECTIONS = set("123")
DEPTHS = set("789")
ERROR_LOCS = set("ndwx")
TERMINALS = set("*#@")
MODIFIERS = set("+-=^")

# Plain-language meaning for the codes we surface in reports.
SERVE_DIR_NAME = {"4": "wide", "5": "body", "6": "T", "0": "unknown"}
DIRECTION_NAME = {"1": "fh_corner", "2": "middle", "3": "bh_corner"}
DEPTH_NAME = {"7": "shallow", "8": "mid", "9": "deep"}
ERROR_LOC_NAME = {"n": "net", "d": "deep", "w": "wide", "x": "wide_deep"}


@dataclass
class Shot:
    """One stroke in a rally, with everything the notation tells us about it."""

    idx: int                 # 1-based stroke number (serve = 1)
    hitter: int              # player number, 1 or 2
    is_serve: bool
    letter: str              # raw shot-type letter ("" for the serve)
    side: str                # "FH" / "BH" / "" (unknown or serve)
    stroke: str              # canonical stroke name ("serve", "forehand", ...)
    direction: "str | None"  # serve dir (4/5/6) or rally dir (1/2/3)
    depth: "str | None"      # 7/8/9 when charted
    modifiers: str           # any of + - = ^
    error_loc: "str | None"  # n/d/w/x when the stroke ended the point in error
    terminal: "str | None"   # * / # / @ when this stroke ended the point


@dataclass
class ParsedPoint:
    """A fully decoded point: the stroke sequence plus how and by whom it ended."""

    raw: str
    serve_in_play: int       # 1 if won/lost on first serve, 2 if on second
    server: int
    returner: int
    shots: "list[Shot]" = field(default_factory=list)
    rally_len: int = 0       # strokes that made contact (serve counts as 1)
    last_hitter: "int | None" = None
    ending_side: str = ""    # FH/BH of the last stroke (for winner/error wings)
    outcome: str = "unknown"  # ace/winner/forced_error/unforced_error/double_fault/...
    winner_by_notation: "int | None" = None
    server_won: "bool | None" = None
    parse_ok: bool = False
    flags: "list[str]" = field(default_factory=list)


def _other(player: int) -> int:
    return 2 if player == 1 else 1


def _new_shot(idx: int, hitter: int, is_serve: bool, letter: str = "") -> Shot:
    if is_serve:
        side, stroke = "", "serve"
    elif letter in FH_LETTERS:
        side, stroke = "FH", FH_LETTERS[letter]
    elif letter in BH_LETTERS:
        side, stroke = "BH", BH_LETTERS[letter]
    else:
        side, stroke = "", OTHER_LETTERS.get(letter, "unknown_shot")
    return Shot(idx, hitter, is_serve, letter, side, stroke, None, None, "", None, None)


def _tokenize(serve_str: str, server: int) -> "tuple[list[Shot], list[str]]":
    """Walk the characters once, emitting strokes with their descriptors."""
    shots: list[Shot] = []
    flags: list[str] = []
    i, n = 0, len(serve_str)

    # Leading non-serve markers (e.g. "c" net-cord lets) occasionally precede the
    # serve direction; skip them but record that we did.
    while i < n and serve_str[i] not in SERVE_DIRS and not serve_str[i].isdigit():
        flags.append(f"lead:{serve_str[i]}")
        i += 1

    if i < n and serve_str[i] in {"4", "5", "6", "0"}:
        shots.append(_new_shot(1, server, is_serve=True))
        shots[-1].direction = serve_str[i]
        i += 1
    else:
        flags.append("no_serve_dir")

    hitter = server
    while i < n:
        ch = serve_str[i]
        if ch in SHOT_LETTERS:
            hitter = _other(hitter)
            shots.append(_new_shot(len(shots) + 1, hitter, is_serve=False, letter=ch))
        elif not shots:
            flags.append(f"stray:{ch}")
        elif ch in DIRECTIONS:
            shots[-1].direction = ch
        elif ch in DEPTHS:
            shots[-1].depth = ch
        elif ch in MODIFIERS:
            shots[-1].modifiers += ch
        elif ch in ERROR_LOCS:
            shots[-1].error_loc = ch
        elif ch in TERMINALS:
            shots[-1].terminal = ch
        else:
            flags.append(f"unk:{ch}")
        i += 1
    return shots, flags


def parse_point(
    first_serve: "str | None",
    second_serve: "str | None",
    server: int,
    pt_winner: "int | None" = None,
) -> ParsedPoint:
    """Decode one charted point. ``pt_winner`` (authoritative) anchors who won."""
    fs = (first_serve or "").strip()
    ss = (second_serve or "").strip()
    server = int(server) if server in (1, 2) else 1
    returner = _other(server)

    # The point is played on the second serve whenever one was charted; the first
    # serve then holds only the (faulted) first delivery.
    use_second = bool(ss)
    serve_str = ss if use_second else fs
    point = ParsedPoint(
        raw=serve_str, serve_in_play=2 if use_second else 1,
        server=server, returner=returner,
    )
    if not serve_str:
        point.flags.append("empty")
        return point

    shots, flags = _tokenize(serve_str, server)
    point.shots = shots
    point.flags = flags
    point.rally_len = len(shots)
    if not shots:
        point.flags.append("no_shots")
        return point

    last = shots[-1]
    point.last_hitter = last.hitter
    point.ending_side = last.side

    if last.terminal == "*":
        point.outcome = "ace" if last.is_serve else "winner"
        point.winner_by_notation = last.hitter
    elif last.terminal == "#":
        point.outcome = "forced_error"
        point.winner_by_notation = _other(last.hitter)
    elif last.terminal == "@":
        point.outcome = "unforced_error"
        point.winner_by_notation = _other(last.hitter)
    elif last.is_serve and last.error_loc is not None:
        # Serve ended in a fault marker with no terminal: a missed serve.
        if point.serve_in_play == 2:
            point.outcome = "double_fault"
            point.winner_by_notation = returner
        else:
            point.outcome = "fault_unfinished"  # 1st-serve fault with no 2nd charted
            point.flags.append("first_fault_no_second")
    else:
        point.outcome = "unknown"
        point.flags.append("no_terminal")

    # Trust the charted winner when present; flag disagreements for diagnostics.
    if pt_winner in (1, 2):
        point.server_won = pt_winner == server
        if point.winner_by_notation is not None and point.winner_by_notation != pt_winner:
            point.flags.append("winner_mismatch")
    elif point.winner_by_notation is not None:
        point.server_won = point.winner_by_notation == server

    point.parse_ok = point.outcome != "unknown" and "no_serve_dir" not in flags
    return point
