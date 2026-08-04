"""Draw a single point's ball path on a small tennis-court SVG.

A charted point tells us, per stroke, three spatial things: lateral placement
(zone 1/2/3 — a right-hander's forehand corner / middle / backhand corner of the
end it lands in), depth (7/8/9 — shallow / mid / deep) for rally shots, and the
serve target (4/5/6 — wide / body / T). This turns that into a court diagram: a
zig-zag of bounce points crossing the net once per stroke, each segment wearing a
pair of small chevrons so the direction of travel reads at a glance, and the final
stroke drawn as a landed winner or a marked miss (into the net / long / wide).

The court geometry and CSS-class names mirror the mini-courts the Pages site
already draws in ``docs/js/court.js`` (a 150×190 field, net at y=95, the
``ct-*`` classes), so an SVG from here drops straight into that theme with
``css_classes=True``; the default is self-contained (inline colours) so the same
call also embeds in a Markdown report or saves as a standalone ``.svg``.

What we can and can't show, honestly:

- Direction is only charted to lane granularity (three lanes), so bounces sit on
  one of three x positions per end, not a continuous coordinate.
- The zig-zag connects successive *bounce* points; it is a placement map, not a
  literal ball-flight arc (the hitter's contact isn't where the previous ball
  bounced). The one contact we draw is the server's, to anchor the first stroke.
- The point string doesn't record whether the server was in the deuce or ad
  court, so which box the serve crosses into is a caller-supplied argument
  (``serve_court``), defaulting to the deuce court. It *is* recoverable from the
  point's game score, though: pass the ``pts`` value to ``point_rally_svg`` and
  it derives the side via ``shots/score.serve_side``.
"""

from dataclasses import dataclass

from match_charting_project.shots.notation import ParsedPoint, Shot, parse_point
from match_charting_project.shots.score import serve_side

# --- Court geometry (matches the site's mini-courts: a 150 x 190 field) -------
# Every coordinate below is shared with docs/js/court.js. The viewBox is not: these
# render at full size in a report and keep the whole field, where the site's thumbnails
# draw at ~88px and crop to the court to buy back the blank margin. Presentation only —
# nothing here follows it.
_W, _H = 150, 190
_LEFT, _RIGHT = 20.0, 130.0          # singles sidelines
_TOP, _BOTTOM = 10.0, 180.0          # baselines
_NET = 95.0                          # net line (mid-court)
_HALF = _NET - _TOP                  # 85: net-to-baseline depth of one half
_SERVICE_F = 0.5                     # service line as a fraction of the half

# Three lateral lanes, seen on screen; zone->lane is resolved per end below.
_LANE_L, _LANE_MID, _LANE_R = 40.0, 75.0, 110.0
# Depth of a rally bounce as a fraction of net->baseline (0 = net, 1 = baseline).
_DEPTH_F = {"7": 0.34, "8": 0.60, "9": 0.86}
_DEPTH_DEFAULT = 0.62                # typical rally ball when depth isn't charted
_SERVE_DEPTH_F = 0.42                # serve lands a touch inside the service line

# Direction wingtips: two small chevrons per segment, at these fractions along it.
_TIP_AT = (0.38, 0.72)
_TIP_BACK = 3.4                      # how far the wings trail behind the apex
_TIP_HALF = 2.5                      # half-width of the V
_TIP_MIN = 9.0                       # shorter than this, no room for a tip at all
_TIP_TWO_MIN = 20.0                  # shorter than this, one centred tip, not two

# Self-contained palette (theme-neutral). Overridable via the `theme` argument;
# ignored when css_classes=True (the page's ct-* classes drive colour instead).
_THEME = {
    "line": "#9aa3a0", "net": "#33403b", "path": "#1a7f4b",
    "win": "#1a7f4b", "miss": "#c2410c", "player": "#1a7f4b", "ink": "#33403b",
}


@dataclass
class _Bounce:
    """One drawn point in the path: where a stroke ended up on the court."""

    x: float
    y: float
    is_serve: bool
    terminal: "str | None"   # * winner / # forced / @ unforced / None (rally continues)
    out: bool                # True when the stroke missed (drawn outside the lines)


def _depth_y(frac: float, target_top: bool) -> float:
    """Map a net->baseline fraction to a y in the target half."""
    return _NET - frac * _HALF if target_top else _NET + frac * _HALF


def _lane_x(direction: "str | None", target_top: bool) -> float:
    """Lateral x for a rally zone (1/2/3), resolved for the end it lands in.

    Zone 1 is a righty's forehand corner, 3 the backhand corner. Because the two
    ends face opposite ways, that corner is screen-left in the far (top) half and
    screen-right in the near (bottom) half — so the mapping mirrors across the net.
    """
    if direction not in ("1", "3"):
        return _LANE_MID                      # middle, or direction not charted
    corner_left = direction == "1"            # zone 1 = FH corner
    if not target_top:                        # near half is mirrored
        corner_left = not corner_left
    return _LANE_L if corner_left else _LANE_R


def _serve_targets_left(court: str) -> bool:
    """Which service box the serve crosses into.

    A serve travels diagonally, so the deuce court (server right of the centre
    mark) crosses into the receiver's *left* box on screen, and the ad court into
    the right box. Anything but ``"ad"`` is treated as the deuce court.
    """
    return str(court).lower() != "ad"


def _serve_x(direction: "str | None", court: str) -> float:
    """Lateral x of a serve target within its diagonal service box.

    T sits by the centre line, wide by the singles sideline, body between —
    mirrored between the deuce (left) and ad (right) boxes. 4=wide, 5=body, 6=T;
    unknown falls back to the body.
    """
    off = {"6": 6.0, "5": 25.0, "4": 45.0}.get(direction, 25.0)   # from centre line
    return _LANE_MID - off if _serve_targets_left(court) else _LANE_MID + off


def _serve_origin_x(court: str) -> float:
    """Where the server stands: right of centre in the deuce court, left in the ad."""
    return _LANE_MID + 20 if _serve_targets_left(court) else _LANE_MID - 20


def _serve_bounce(direction: "str | None", court: str) -> _Bounce:
    """Serve target in its diagonal service box (deuce unless court='ad')."""
    y = _depth_y(_SERVE_DEPTH_F, target_top=True)
    return _Bounce(_serve_x(direction, court), y, is_serve=True, terminal=None, out=False)


def _serve_miss(direction: "str | None", error_loc: "str | None", court: str) -> _Bounce:
    """Place a faulted serve just outside the service box per its error location."""
    x = _serve_x(direction, court)
    if error_loc == "n":                       # into the net
        return _Bounce(x, _NET, is_serve=True, terminal=None, out=True)
    if error_loc == "w":                       # wide of the box's outer sideline
        x = _LEFT - 5 if _serve_targets_left(court) else _RIGHT + 5
        return _Bounce(x, _depth_y(_SERVE_DEPTH_F, True), is_serve=True, terminal=None, out=True)
    # long (d) or unspecified: just past the service line
    return _Bounce(x, _depth_y(_SERVICE_F + 0.1, True), is_serve=True, terminal=None, out=True)


def _miss_bounce(direction: "str | None", target_top: bool, error_loc: "str | None",
                 terminal: str) -> _Bounce:
    """Place a missed stroke just outside the lines per its error location."""
    x = _lane_x(direction, target_top)
    if error_loc == "n":                       # into the net: stop at the net line
        return _Bounce(x, _NET, is_serve=False, terminal=terminal, out=True)
    if error_loc in ("w", "x"):                # wide: outside the nearer sideline
        x = _LEFT - 5 if x < _LANE_MID else _RIGHT + 5
    if error_loc in ("d", "x") or error_loc is None:
        frac = 1.08                            # long: just past the baseline
    else:
        frac = _DEPTH_DEFAULT
    return _Bounce(x, _depth_y(frac, target_top), is_serve=False, terminal=terminal, out=True)


def _bounces_from_shots(shots: "list[Shot]", server_at_bottom: bool,
                        serve_court: str) -> "list[_Bounce]":
    """Turn decoded strokes into ordered bounce points (one per stroke)."""
    out: list[_Bounce] = []
    for i, s in enumerate(shots):
        # Server hits from the bottom, so odd strokes land in the top half.
        target_top = (i % 2 == 0) if server_at_bottom else (i % 2 == 1)
        # A stroke missed if it ended the point in error, or (for a serve) faulted
        # with just a location and no terminal symbol.
        is_miss = s.terminal in ("#", "@") or s.error_loc is not None
        if s.is_serve:
            if is_miss:
                out.append(_serve_miss(s.direction, s.error_loc, serve_court))
            else:
                b = _serve_bounce(s.direction, serve_court)
                b.terminal = s.terminal        # an ace still bounces in the box
                out.append(b)
        elif is_miss:
            out.append(_miss_bounce(s.direction, target_top, s.error_loc, s.terminal))
        else:
            frac = _DEPTH_F.get(s.depth or "", _DEPTH_DEFAULT)
            out.append(_Bounce(_lane_x(s.direction, target_top), _depth_y(frac, target_top),
                               is_serve=False, terminal=s.terminal, out=False))
    return out


# --- Token adapter: the shot alphabet used across the experiments -------------
# Tokens look like "svW" / "svB" / "svT" (serve wide/body/T) or "<F|B|?><d|s|v|o><dir>"
# e.g. "Fd1" (forehand drive to zone 1), "Bs·" (backhand slice, direction uncharted).
_SERVE_TOKEN_DIR = {"W": "4", "B": "5", "T": "6"}


def _shots_from_tokens(tokens: "list[str]") -> "list[Shot]":
    """Build minimal Shots from shot-alphabet tokens (no depth/terminal in them)."""
    shots: list[Shot] = []
    for i, tok in enumerate(tokens):
        is_serve = tok.startswith("sv")
        direction = _SERVE_TOKEN_DIR.get(tok[2:], None) if is_serve else (
            tok[2] if len(tok) > 2 and tok[2] in "123" else None)
        shots.append(Shot(idx=i + 1, hitter=0, is_serve=is_serve, letter="", side="",
                          stroke="serve" if is_serve else "", direction=direction,
                          depth=None, modifiers="", error_loc=None, terminal=None))
    return shots


# --- SVG assembly -------------------------------------------------------------

def _f(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _tip_elems(x1: float, y1: float, x2: float, y2: float, attrs: str) -> "list[str]":
    """Small chevrons along a segment, pointing from (x1,y1) toward (x2,y2).

    A zig-zag of bounces is ambiguous on its own — the same shape reads either
    way round — so each segment carries two wingtips showing which way the ball
    went. Short segments get one, and a hair-thin one none, rather than a
    cluttered smear of arrowheads.
    """
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length < _TIP_MIN:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux                                   # unit normal: the wings' spread
    els: list[str] = []
    for t in (_TIP_AT if length >= _TIP_TWO_MIN else (0.5,)):
        ax, ay = x1 + dx * t, y1 + dy * t              # apex, on the line
        bx, by = ax - _TIP_BACK * ux, ay - _TIP_BACK * uy   # the wings trail behind it
        els.append(f'<path d="M{_f(bx + _TIP_HALF * nx)} {_f(by + _TIP_HALF * ny)} '
                   f'L{_f(ax)} {_f(ay)} '
                   f'L{_f(bx - _TIP_HALF * nx)} {_f(by - _TIP_HALF * ny)}" fill="none" '
                   f'stroke-linecap="round" stroke-linejoin="round" {attrs}/>')
    return els


def _court_elems(css: bool, th: dict) -> "list[str]":
    """The static court: sidelines, net, service boxes, centre marks."""
    ln = 'class="ct-line"' if css else f'stroke="{th["line"]}" stroke-width="1.2" fill="none"'
    net = 'class="ct-net"' if css else f'stroke="{th["net"]}" stroke-width="2.2"'
    sy_t, sy_b = _depth_y(_SERVICE_F, True), _depth_y(_SERVICE_F, False)
    return [
        f'<rect x="{_LEFT}" y="{_TOP}" width="{_RIGHT - _LEFT}" height="{_BOTTOM - _TOP}" {ln}/>',
        f'<line x1="{_LEFT}" y1="{_f(sy_t)}" x2="{_RIGHT}" y2="{_f(sy_t)}" {ln}/>',
        f'<line x1="{_LEFT}" y1="{_f(sy_b)}" x2="{_RIGHT}" y2="{_f(sy_b)}" {ln}/>',
        f'<line x1="{_LANE_MID}" y1="{_f(sy_t)}" x2="{_LANE_MID}" y2="{_f(sy_b)}" {ln}/>',
        f'<line x1="{_LANE_MID}" y1="{_TOP}" x2="{_LANE_MID}" y2="{_f(_TOP + 4)}" {ln}/>',
        f'<line x1="{_LANE_MID}" y1="{_f(_BOTTOM - 4)}" x2="{_LANE_MID}" y2="{_BOTTOM}" {ln}/>',
        f'<line x1="{_LEFT}" y1="{_NET}" x2="{_RIGHT}" y2="{_NET}" {net}/>',
    ]


def _path_elems(start: "tuple[float, float]", bounces: "list[_Bounce]",
                css: bool, th: dict, numbered: bool) -> "list[str]":
    """The ball path: one segment per stroke, faint→bold, wingtipped for direction,
    with a terminal marker on the last bounce."""
    els: list[str] = []
    n = len(bounces)
    px, py = start
    # Server's contact, to anchor the first stroke.
    els.append(f'<circle cx="{_f(px)}" cy="{_f(py)}" r="2.3" fill="none" '
               + ('class="ct-player"/>' if css else f'stroke="{th["player"]}" stroke-width="1.4"/>'))
    for i, b in enumerate(bounces):
        last = i == n - 1
        miss = b.out
        col = th["miss"] if miss else th["path"]
        op = 0.4 + 0.6 * ((i + 1) / n)         # ramp so the eye follows the order
        if css:
            cls = "ct-shot" + ("" if last else " faint")
            stroke = f'class="{cls}"' + (f' stroke="{th["miss"]}"' if miss else "")
            # Tips stay solid on a dashed miss, and never inherit its dash pattern.
            tip = 'class="ct-tip' + ("" if last else " faint") + '"' \
                  + (f' stroke="{th["miss"]}"' if miss else "")
        else:
            stroke = f'stroke="{col}" stroke-width="{1.9 if last else 1.4}" ' \
                     f'opacity="{op:.2f}"' + (' stroke-dasharray="3 2"' if miss else "")
            tip = f'stroke="{col}" stroke-width="{1.4 if last else 1.1}" opacity="{op:.2f}"'
        els.append(f'<line data-shot="{i + 1}" x1="{_f(px)}" y1="{_f(py)}" '
                   f'x2="{_f(b.x)}" y2="{_f(b.y)}" {stroke} fill="none"/>')
        els += _tip_elems(px, py, b.x, b.y, tip)
        if numbered:
            els.append(f'<text x="{_f(b.x)}" y="{_f(b.y - 3)}" font-size="7" '
                       f'text-anchor="middle" fill="{th["ink"]}">{i + 1}</text>')
        px, py = b.x, b.y
    # Terminal marker on the last bounce: a dot for a winner, an × for a miss.
    end = bounces[-1] if bounces else None
    if end is not None:
        if end.out:
            r = 3.0
            els.append(f'<line x1="{_f(end.x - r)}" y1="{_f(end.y - r)}" x2="{_f(end.x + r)}" '
                       f'y2="{_f(end.y + r)}" stroke="{th["miss"]}" stroke-width="1.6"/>')
            els.append(f'<line x1="{_f(end.x - r)}" y1="{_f(end.y + r)}" x2="{_f(end.x + r)}" '
                       f'y2="{_f(end.y - r)}" stroke="{th["miss"]}" stroke-width="1.6"/>')
        elif end.terminal == "*":
            els.append(f'<circle cx="{_f(end.x)}" cy="{_f(end.y)}" r="2.8" '
                       f'fill="{th["win"]}"/>')
    return els


def rally_svg(source, *, server: int = 1, serve_court: str = "deuce",
              css_classes: bool = False, numbered: bool = False,
              caption: "str | None" = None, theme: "dict | None" = None) -> str:
    """Render a point's ball path as a court SVG string.

    ``source`` may be a :class:`ParsedPoint`, a list of :class:`Shot` (its
    ``shots``), a list of shot-alphabet tokens (``["svW", "Fd1", ...]``), or a raw
    serve-column string (e.g. ``"4f2d#"``), which is parsed with ``server``.

    ``serve_court`` is ``"deuce"`` (server right of the centre mark, crossing into
    the left box) or ``"ad"`` (mirror image) — the point string doesn't record it,
    so the caller supplies it. ``css_classes`` emits the site's ``ct-*`` classes
    instead of inline colours; ``numbered`` labels each bounce with its stroke
    number; ``caption`` adds a line of text under the court; ``theme`` overrides
    the self-contained palette.
    """
    th = {**_THEME, **(theme or {})}
    if isinstance(source, str):
        source = parse_point(source, None, server)
    if isinstance(source, ParsedPoint):
        shots, server_at_bottom = source.shots, True
    elif source and isinstance(source[0], Shot):
        shots, server_at_bottom = list(source), True
    else:                                       # token list (may start mid-rally)
        shots, server_at_bottom = _shots_from_tokens(list(source)), True
    if not shots:
        shots = []

    bounces = _bounces_from_shots(shots, server_at_bottom, serve_court)
    # The server contacts from behind their baseline, to one side of the centre
    # mark, and serves diagonally into the opposite box.
    start = (_serve_origin_x(serve_court), _BOTTOM - 4)

    h = _H + (14 if caption else 0)
    parts = [f'<svg viewBox="0 0 {_W} {h}" xmlns="http://www.w3.org/2000/svg" '
             f'width="{_W}" height="{h}" role="img">']
    parts += _court_elems(css_classes, th)
    parts += _path_elems(start, bounces, css_classes, th, numbered)
    if caption:
        parts.append(f'<text x="{_LANE_MID}" y="{_H + 9}" font-size="8" '
                     f'text-anchor="middle" fill="{th["ink"]}">{caption}</text>')
    parts.append("</svg>")
    return "".join(parts)


def point_rally_svg(first_serve: "str | None", second_serve: "str | None",
                    server: int, pt_winner: "int | None" = None, *,
                    serve_court: str = "deuce", pts: "str | None" = None,
                    **kwargs) -> str:
    """Convenience: parse a points-table row (mirrors ``parse_point``) then render.

    ``serve_court`` ("deuce"/"ad") is which service box the serve crosses into.
    The raw notation doesn't carry it, but the ``points`` table does implicitly:
    pass the row's ``pts`` (game score) and the side is derived via
    :func:`match_charting_project.shots.score.serve_side` (an unparseable score
    falls back to ``serve_court``). Passing ``serve_court`` directly still works
    when the caller has already resolved the side.
    """
    if pts is not None:
        side = serve_side(pts)
        if side in ("deuce", "ad"):
            serve_court = side
    return rally_svg(parse_point(first_serve, second_serve, server, pt_winner),
                     server=server, serve_court=serve_court, **kwargs)
