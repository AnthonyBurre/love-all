"""Per-match sidecars: the JSON the panel reads when the match in front of it is charted.

One file per charted match under ``docs/data/matches/<match_id>.json``, holding a
win-probability curve and a two-sided box score. The panel fetches exactly one of them,
on open, and only for a match that already carries a ``chart_id``.

Sidecars rather than tables in ``insights.duckdb``, because ``docs/js/db.js`` pulls that
file down whole into an ArrayBuffer before the first query: every byte in it is paid by
every visitor on load, and this data is read by roughly one panel open in ten. As
separate files the cost falls only on the open that wants them — about 6 KB, once.

Written for every row of ``charted_matches``, not for the subset a current
``brackets.json`` happens to reference. The two are produced by different jobs: this one
runs in the weekly insights build, which is where ``tennis.duckdb`` exists, and the
brackets are assembled hourly from the insights release alone. Since ``chart_id`` is read
out of the same ``charted_matches`` table (see ``build_brackets._insights``), generating
from that table is what guarantees the two can never disagree — a match cannot show a
chart link with no sidecar behind it. The surplus files are never fetched.

None of these figures is gated on sample size, which is the opposite of every rate the
career panel prints. A career rate is an estimator of a latent skill and needs enough
points behind it to mean anything; a match rate is a measurement of what happened in the
match, and 70 service points is the whole population, not a sample of it.

Run: ``match-charting-project site build-match-details``.
"""

import json
from collections import Counter, defaultdict

import duckdb

from match_charting_project.paths import DB_PATH, PROJECT_ROOT
from match_charting_project.shots.notation import parse_point, serve_dir
from match_charting_project.shots.score import serve_side
from match_charting_project.winprob_match import (
    blend,
    parse_score,
    predictive_models,
    walk_forward_strength,
)

OUT_DIR = PROJECT_ROOT / "data" / "match_details"
SIDES = ("deuce", "ad")
DIRS = ("4", "5", "6")          # wide / body / T, in the order the panel draws them

# The game scores at which the returner is one point from the break, in the server-first
# notation the ``pts`` column is written in. Same reading as the score-aware eval's
# ``_BREAK`` (``experiments/score_aware_eval/model.py``); keep the two in step.
#
# A point is a break point every time it is played at one of these scores, so a deuce game
# that reaches advantage-returner three times supplies three of them. That is the
# convention every scoreboard quotes, and it is the one the source's own ``bk_pts`` column
# uses: derived this way the two agree on 3,081 of the 3,098 player-matches in the charted
# corpus (99.4%), and on ``bp_saved`` for 3,087 of them. The seventeen that disagree are
# all cases where a game supplied a second break point that the source did not count; the
# rule here is applied identically to every match rather than inherited match by match,
# which is what makes the number comparable between the two players of a panel.
#
# Tiebreaks are excluded for free: their scores are integer counts, so none of them can
# match a game token, and a set is not broken inside one anyway.
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
        "first_in": 0, "first_won": 0, "second_pts": 0, "second_won": 0,
        "ret_pts": 0, "ret_won": 0, "ret_winners": 0,
        "sv_games": 0, "held": 0,
        # Break points from the server's end: how many were played against them, and how
        # many of those they won. The other player's chances are the same two numbers read
        # from the other side, so the panel derives "converted 2 of 6" from the opponent's
        # row rather than carrying a second pair that could disagree with it.
        "bp_faced": 0, "bp_saved": 0,
        "pts_won": 0, "_len_won": 0,
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
    if p.outcome == "ace":
        srv_side["aces"] += 1
    elif p.outcome == "double_fault":
        srv_side["dfs"] += 1
    elif p.outcome == "winner":
        # The return ring's outright core: a point won on the return stroke itself.
        # Same rule as the career figure (build_insights._RETURN_WINNER_SQL).
        if p.rally_len == 2 and p.last_hitter == ret:
            ret_side["ret_winners"] += 1


def _finish_side(s: dict) -> dict:
    """Turn the running tallies into the shape the panel reads."""
    won = s.pop("pts_won")
    total_len = s.pop("_len_won")
    # Average length of the points this player *won*, so the two sides differ — the career
    # figure averages every point either player played and is the same number for both.
    s["len_won"] = round(total_len / won, 2) if won else None
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

    # The prior is ``walk_forward_strength``: each player's serve and return rates over the
    # matches charted *strictly before this one's day*, shrunk toward the tour mean by 100
    # pseudo-counts, then combined into a point-win probability apiece.
    #
    # Not ``current_strength``, which is the whole-career rate and the wrong tool twice over.
    # It has no pseudo-count, so a player charted once opens with a rate read off a single
    # afternoon — and it is computed over every charted match including *this* one, so the
    # match sits in its own prior and the curve knows a little of how it ends before it
    # starts. That function says as much in its own docstring: its stated consumer is the
    # panel's two rings, which are withheld below 2,000 charted points, so the thin players
    # a pseudo-count would protect never reach it. Nothing gates this path, so it needs the
    # estimator built for it.
    pa, pb = pq.get(mid, (mu[gender], mu[gender]))
    # Averaged over the spread of strengths the match could have been played at, rather than
    # evaluated once at the best guess — see winprob_match.predictive_models. The tree is
    # exact given a point-win probability and sharply non-linear in it, and that probability
    # is not a constant a player carries between matches: measured against its own
    # prediction it moves 6.6 points either way beyond coin-flipping. Read at a single value
    # the answer compounds a certainty nothing supports, and the panel drew flat lines along
    # the top of the box for matches that were not remotely settled.
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
    ins = PROJECT_ROOT / "data" / "insights.duckdb"
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
