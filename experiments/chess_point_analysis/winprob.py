"""An empirical "engine eval" for a tennis point: P(server wins | rally state).

A chess engine assigns every position a value (win probability for the side to
move). The tennis analogue here is a value function over *rally states*: given how
far the point has progressed and what the last stroke looked like, what fraction
of the time does the server go on to win? Estimated purely by frequency over the
charted points -- which works because the rally states are coarse and the points
number in the millions (the opposite regime from chess: shallow trees, huge n).

State features, ordered general -> specific (the backoff order). Each adds one
field; rare deep states shrink toward their coarser parent (an empirical-Bayes
pull, the direct analogue of an opening explorer falling back to broader stats on
a rare line):

    serve_in_play  1st- or 2nd-serve point
    shot_index     how many strokes have landed (capped), i.e. the "ply"
    to_hit         whose turn it is next -- server (S) or returner (R)
    wing           the wing of the last stroke (serve / FH / BH)
    kind           drive / slice / net (volley,OH,half-volley) / other -- the
                   drive-vs-slice distinction is well charted (~12% slices) and
                   strongly shapes the rally
    direction      where the last stroke went (serve dir, or 1/2/3)
    approach       1 if it was an approach / net-position stroke (+/- modifier)
    depth          return/shot depth 7/8/9 (charted on ~74% of returns)

The same traversal records, for each state, which stroke tends to come next and
how the point turns out -- the "opening explorer" view of the eval.
"""

from collections import defaultdict

from parser import ParsedPoint, _other, parse_point

CAP = 8          # cap the ply so deep rallies share buckets (keeps cells dense)
K_SHRINK = 50    # pseudo-count pulling a state toward its parent estimate
EXPLORE_LEVEL = 6  # prefix length used as the opening-explorer state key

# Stroke "kind" groups: drive vs slice is high-signal and well charted; volleys,
# overheads and half-volleys are inherently net strokes.
_DRIVE = set("fb")
_SLICE = set("rs")
_NET = set("vzopuy")


def _kind(letter: str, is_serve: bool) -> str:
    if is_serve:
        return "serve"
    if letter in _DRIVE:
        return "drive"
    if letter in _SLICE:
        return "slice"
    if letter in _NET:
        return "net"
    return "other"


def iter_parsed_points(con, where: str = "", sample: "int | None" = None):
    """Yield ParsedPoint rows from the DuckDB points table."""
    sql = (
        "SELECT svr, first_serve, second_serve, pt_winner FROM points "
        "WHERE svr IN (1,2) AND pt_winner IN (1,2)"
    )
    if where:
        sql += f" AND {where}"
    if sample:
        sql += f" USING SAMPLE reservoir({int(sample)} ROWS) REPEATABLE (1)"
    for svr, fs, ss, win in con.execute(sql).fetchall():
        yield parse_point(fs, ss, svr, win)


class WinProbModel:
    """Frequency-table value function with parent-shrinkage smoothing."""

    def __init__(self, k_shrink: int = K_SHRINK, cap: int = CAP):
        self.K = k_shrink
        self.cap = cap
        # [n, server_wins] counters at two granularities.
        self.point_counts: dict = defaultdict(lambda: [0, 0])  # (), (sip,)
        self.pos_counts: dict = defaultdict(lambda: [0, 0])    # L2..L5 state keys
        # state -> next-stroke descriptor -> [n, server_wins]  (explorer view)
        self.explore: dict = defaultdict(lambda: defaultdict(lambda: [0, 0]))

    # -- feature extraction -------------------------------------------------
    def _feats(self, point: ParsedPoint, j: int) -> tuple:
        """Ordered (general->specific) features for the position after j strokes."""
        shots = point.shots
        last = shots[j - 1]
        nxt = shots[j].hitter if j < len(shots) else _other(last.hitter)
        to_hit = "S" if nxt == point.server else "R"
        wing = "SV" if last.is_serve else (last.side or "XX")
        kind = _kind(last.letter, last.is_serve)
        direction = last.direction or "?"
        approach = 1 if ("+" in last.modifiers or "-" in last.modifiers) else 0
        depth = last.depth or "-"
        return (point.serve_in_play, min(j, self.cap), to_hit,
                wing, kind, direction, approach, depth)

    @staticmethod
    def _next_desc(shot) -> tuple:
        return ("SV" if shot.is_serve else (shot.side or "XX"), shot.direction or "?")

    # -- fitting ------------------------------------------------------------
    def add_point(self, point: ParsedPoint) -> None:
        if not point.parse_ok or point.server_won is None or not point.shots:
            return
        sip = point.serve_in_play
        w = 1 if point.server_won else 0
        for key in ((), (sip,)):
            c = self.point_counts[key]
            c[0] += 1
            c[1] += w
        n = len(point.shots)
        for j in range(1, n):  # non-terminal positions only
            feats = self._feats(point, j)
            for k in range(2, len(feats) + 1):  # prefixes (sip,ply) ... full
                c = self.pos_counts[feats[:k]]
                c[0] += 1
                c[1] += w
            e = self.explore[feats[:EXPLORE_LEVEL]][self._next_desc(point.shots[j])]
            e[0] += 1
            e[1] += w

    def fit(self, points) -> "WinProbModel":
        for p in points:
            self.add_point(p)
        return self

    # -- evaluation ---------------------------------------------------------
    def base(self, sip: int) -> float:
        """Pre-serve value: P(server wins) for a 1st/2nd-serve point."""
        glob = self.point_counts[()]
        g = glob[1] / glob[0] if glob[0] else 0.6
        c = self.point_counts.get((sip,))
        if not c or not c[0]:
            return g
        return (c[1] + self.K * g) / (c[0] + self.K)

    def position_value(self, point: ParsedPoint, j: int) -> float:
        """Shrunk empirical P(server wins) for the state after j strokes."""
        feats = self._feats(point, j)
        est = self.base(feats[0])
        for k in range(2, len(feats) + 1):  # back off from coarse to specific
            c = self.pos_counts.get(feats[:k])
            if c and c[0]:
                est = (c[1] + self.K * est) / (c[0] + self.K)
        return est

    def point_values(self, point: ParsedPoint) -> "list[float]":
        """Value at every position 0..n; ends at the realized 0/1 result."""
        n = len(point.shots)
        vals = [self.base(point.serve_in_play)]
        vals.extend(self.position_value(point, j) for j in range(1, n))
        vals.append(1.0 if point.server_won else 0.0)
        return vals

    def shot_wpa(self, point: ParsedPoint) -> "list[dict]":
        """Win-probability added by each stroke, from the *hitter's* viewpoint.

        ``server_delta`` is the change in P(server wins); ``wpa`` flips its sign
        for returner strokes so that positive always means "helped the hitter".
        Sums of ``server_delta`` telescope to (result - pre-serve value).
        """
        vals = self.point_values(point)
        out = []
        for j in range(1, len(point.shots) + 1):
            shot = point.shots[j - 1]
            server_delta = vals[j] - vals[j - 1]
            is_server = shot.hitter == point.server
            out.append({
                "idx": shot.idx, "hitter": shot.hitter,
                "role": "server" if is_server else "returner",
                "stroke": shot.stroke, "side": shot.side,
                "v_before": vals[j - 1], "v_after": vals[j],
                "server_delta": server_delta,
                "wpa": server_delta if is_server else -server_delta,
                "terminal": shot.terminal,
            })
        return out

    def explore_state(self, key) -> "list[dict]":
        """Opening-explorer view: next strokes from a state + server win%.

        ``key`` is a prefix of the feature tuple of length ``EXPLORE_LEVEL``,
        e.g. ``(serve_in_play, ply, to_hit, wing, kind, direction)``.
        """
        d = self.explore.get(tuple(key), {})
        rows = [{"next_side": k[0], "next_dir": k[1], "n": v[0],
                 "server_win_pct": v[1] / v[0]} for k, v in d.items()]
        return sorted(rows, key=lambda r: -r["n"])
