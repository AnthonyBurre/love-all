"""Per-match sidecars: the JSON the panel reads when the match in front of it is charted.

One file per charted match under ``docs/data/matches/<match_id>.json``, holding a
win-probability curve and a two-sided box score. The panel fetches one, on open, only for a
match with a ``chart_id``. Separate files rather than tables in ``insights.duckdb``, which
every visitor downloads whole; this way only the open that needs it pays (~6 KB).

Written for every row of ``charted_matches``, the same table ``chart_id`` comes from (see
``build_brackets._insights``), so a chart link always has a sidecar behind it.

No figure here is gated on sample size: a match rate is a measurement of what happened, not
an estimate of a skill.

Run: ``match-charting-project site build-match-details``.
"""

import json
from collections import Counter, defaultdict

import duckdb

from match_charting_project.paths import DATA_DIR, DB_PATH
from match_charting_project.shots.notation import (
    blank_mix,
    fold_shot_mix,
    parse_point,
    serve_dir,
)
from match_charting_project.shots.score import serve_side
from match_charting_project.winprob_match import (
    blend,
    parse_score,
    predictive_models,
    walk_forward_strength,
)

OUT_DIR = DATA_DIR / "match_details"
SIDES = ("deuce", "ad")
DIRS = ("4", "5", "6")          # wide / body / T, in the order the panel draws them

# Game scores (server-first, as in ``pts``) at which the returner is one point from the break.
# Same set as the score-aware eval's ``_BREAK`` (``experiments/score_aware_eval/model.py``);
# keep them in step. Every point played at one counts, so a deuce game can supply several.
# This matches the source's ``bk_pts`` on 3,081 of 3,098 player-matches (99.4%); the rest are
# games where the source missed a repeat break point. Tiebreak scores are integers, so they
# never match.
_BREAK = frozenset({"0-40", "15-40", "30-40", "40-AD"})

_POINTS_SQL = (
    "SELECT p.match_id, p.pt, p.svr, p.set1, p.set2, p.gm1, p.gm2, p.pts, "
    "       p.first_serve, p.second_serve, p.pt_winner "
    "FROM points p JOIN charted USING (match_id) "
    "WHERE p.svr IN (1, 2) AND p.pt_winner IN (1, 2) "
    "ORDER BY p.match_id, p.pt"
)


def _blank_side() -> dict:
    return {
        "serve_pts": 0, "serve_won": 0, "aces": 0, "dfs": 0,
        # The aces again, split by which delivery struck them. They ride beside the tallies
        # of the column each one is drawn inside on the serve plot — first_in and second_pts
        # — because that is the denominator each share is taken over.
        "aces_first": 0, "aces_second": 0,
        "first_in": 0, "first_won": 0, "second_pts": 0, "second_won": 0,
        "ret_pts": 0, "ret_won": 0, "ret_winners": 0,
        "sv_games": 0, "held": 0,
        # Break points from the server's end: how many were played against them, and how
        # many of those they won. The other player's chances are the same two numbers read
        # from the other side, so the panel derives "converted 2 of 6" from the opponent's
        # row rather than carrying a second pair that could disagree with it.
        "bp_faced": 0, "bp_saved": 0,
        "pts_won": 0, "_len_won": 0, "_len_won_n": 0,
        # The shot mix, over every stroke the player hit that was not a serve — the return
        # among them. The same tallies the career aggregate keeps off the same shared walk
        # (notation.fold_shot_mix), because the panel prints one under the other: the
        # match's rate, and the player's career rate as the anchor beneath it.
        **blank_mix(),
        # First-delivery placement per court, counted wide/body/T. The first delivery
        # whether or not it landed, which is the convention the career mix uses
        # (serve_tendencies reads serve_dir off the raw first_serve column), so the two
        # are the same measurement over different windows and can be shown together.
        "dirs": {s: [0, 0, 0] for s in SIDES},
        "dirs2": {s: [0, 0, 0] for s in SIDES},
    }


def _fold_point(sides: dict, row: tuple, games: dict) -> None:
    """Add one point to both players' tallies."""
    _, pt, svr, s1, s2, g1, g2, pts, fs, ss, win = row
    ret = 2 if svr == 1 else 1
    srv_side, ret_side = sides[svr], sides[ret]

    # The last point folded into a game is the one that decided it, so recording the
    # server and the winner per game key and reading it after the walk gives holds
    # without a second pass or a game-boundary detector.
    games[(s1, s2, g1, g2)] = (svr, win)

    if pts in _BREAK:
        srv_side["bp_faced"] += 1
        if win == svr:
            srv_side["bp_saved"] += 1

    srv_side["serve_pts"] += 1
    ret_side["ret_pts"] += 1
    if win == svr:
        srv_side["serve_won"] += 1
    else:
        ret_side["ret_won"] += 1
    sides[win]["pts_won"] += 1

    second = bool((ss or "").strip())
    if second:
        srv_side["second_pts"] += 1
        if win == svr:
            srv_side["second_won"] += 1
    else:
        srv_side["first_in"] += 1
        if win == svr:
            srv_side["first_won"] += 1

    d1 = serve_dir(fs)
    side = serve_side(pts)
    if side in SIDES and d1 in DIRS:
        srv_side["dirs"][side][DIRS.index(d1)] += 1
    if second:
        d2 = serve_dir(ss)
        if side in SIDES and d2 in DIRS:
            srv_side["dirs2"][side][DIRS.index(d2)] += 1

    p = parse_point(fs, ss, svr, win)
    if not p.parse_ok:
        return
    sides[win]["_len_won"] += p.rally_len
    sides[win]["_len_won_n"] += 1
    if p.outcome == "ace":
        srv_side["aces"] += 1
        srv_side["aces_second" if second else "aces_first"] += 1
    elif p.outcome == "double_fault":
        srv_side["dfs"] += 1
    elif p.outcome == "winner":
        # The return ring's outright core: a point won on the return stroke itself.
        # Same rule as the career figure (build_insights._RETURN_WINNER_SQL).
        if p.rally_len == 2 and p.last_hitter == ret:
            ret_side["ret_winners"] += 1

    fold_shot_mix(p, lambda hitter: sides[hitter])


def _finish_side(s: dict) -> dict:
    """Turn the running tallies into the shape the panel reads."""
    won = s.pop("pts_won")
    total_len = s.pop("_len_won")
    parsed_won = s.pop("_len_won_n")
    s["len_won"] = round(total_len / parsed_won, 2) if parsed_won else None
    s["pts_won"] = won
    return s


def _match_payload(mid: str, meta: dict, rows: list, pq: dict, mu: dict) -> "dict | None":
    p1, p2, gender, best_of = meta["p1"], meta["p2"], meta["gender"], meta["best_of"]
    sides = {1: _blank_side(), 2: _blank_side()}
    games: dict = {}
    for row in rows:
        _fold_point(sides, row, games)

    served, held = Counter(), Counter()
    for svr, win in games.values():
        served[svr] += 1
        if win == svr:
            held[svr] += 1
    for n in (1, 2):
        sides[n]["sv_games"] = served[n]
        sides[n]["held"] = held[n]

    # The prior is ``walk_forward_strength``: each player's serve and return rates over
    # matches charted strictly before this one's day, shrunk toward the tour mean by 100
    # pseudo-counts. Not ``current_strength``, which is unshrunk and includes this match.
    pa, pb = pq.get(mid, (mu[gender], mu[gender]))
    # Averaged over the spread of strengths the match could be played at (see
    # winprob_match.predictive_models), since the tree is sharply non-linear in them.
    models = predictive_models(pa, pb, best_of)

    curve, sets, prev = [], [], None
    for row in rows:
        _, pt, svr, s1, s2, g1, g2, pts, _, _, _ = row
        score = parse_score(svr, s1, s2, g1, g2, pts)
        if score is None:
            continue
        curve.append([int(pt),
                      round(blend(models, lambda m: m.wp(score)), 4),
                      round(blend(models, lambda m: m.leverage(score)), 3)])
        # A set boundary is where the set counts change, recorded as the point index it
        # happened at so the chart can rule the curve without re-deriving the score.
        if prev is not None and (s1, s2) != prev:
            sets.append(int(pt))
        prev = (s1, s2)
    if not curve:
        return None

    return {
        "v": 1,
        "id": mid,
        "p": [p1, p2],
        "best_of": best_of,
        "charted_by": meta["charted_by"],
        "wp": {
            "prior": [round(pa, 4), round(pb, 4)],
            "pre": round(blend(models, lambda m: m.pre_match()), 4),
            # A fallback for the curve's endpoint: every wp in the list is the state
            # *before* a point, so the last one is not the result. The panel prefers the
            # draw's own winner, which is right for a retirement too — see build() above.
            "won": meta["won"],
            "curve": curve,
            "sets": sets,
        },
        "s": [_finish_side(sides[1]), _finish_side(sides[2])],
    }


def build() -> int:
    """Write one sidecar per charted match. Returns the number of files written."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    # One date-ordered pass over the whole point corpus, which is where the no-leakage
    # property comes from: a match is scored only off the matches that came before it.
    pq, mu = walk_forward_strength(con)
    ins = DATA_DIR / "insights.duckdb"
    if not ins.exists():
        con.close()
        raise SystemExit("data/insights.duckdb missing — run site build-insights first")
    # ATTACH takes no parameters, so the path is inlined; it is this repo's own build
    # artifact, not input.
    con.execute(f"ATTACH '{ins}' AS ins (READ_ONLY)")
    con.execute("CREATE TEMP TABLE charted AS SELECT match_id FROM ins.charted_matches")

    meta = {}
    for mid, p1, p2, g, bo, by in con.execute(
            "SELECT m.match_id, m.player1, m.player2, m.gender, m.best_of, m.charted_by "
            "FROM matches m JOIN charted USING (match_id)").fetchall():
        # A missing best_of defaults to three: the shorter format is the common one, and
        # the field is only blank on a handful of rows.
        meta[mid] = {"p1": p1, "p2": p2, "gender": g,
                     "best_of": int(bo) if bo in (3, 5) else 3,
                     "charted_by": (by or "").strip() or None}

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*.json"):
        stale.unlink()          # fresh set: a match dropped upstream must not ship forever

    rows_by_match: dict = defaultdict(list)
    cur = con.execute(_POINTS_SQL)
    while batch := cur.fetchmany(200_000):
        for row in batch:
            rows_by_match[row[0]].append(row)
    con.close()

    written = 0
    for mid, rows in rows_by_match.items():
        if mid not in meta:
            continue
        # Who won the last charted point. That is the winner of the match whenever a match
        # ends by someone winning one, and not otherwise: two of the 121 matches the site
        # currently holds are retirements, where the player who retired had just taken the
        # last point and was two sets up. So this is a fallback only — the panel reads the
        # result off the draw, which is the thing that actually knows (see wpChart).
        meta[mid]["won"] = int(rows[-1][10])
        payload = _match_payload(mid, meta[mid], rows, pq, mu)
        if payload is None:
            continue
        (OUT_DIR / f"{mid}.json").write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        written += 1
    return written
