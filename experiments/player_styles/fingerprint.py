"""Per-player style fingerprints from the decoded point notation.

A player's *style* lives in their shot tendencies: where they serve, how much they
slice, whether they come forward, how long their points run, how aggressively they
end them. This turns each player into a feature vector built from the parsed strokes
(reusing the graduated ``match_charting_project.shots`` decoder), which the
clustering step then groups into archetypes.

Features are rates, chosen to be reasonably handedness-invariant (shot-type mix,
depth, rally length, aggression) so lefties and righties aren't split spuriously.
Caveat: a player's shots are partly reactive to the opponent, so a fingerprint
reflects "style in context", not an intrinsic constant.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd  # noqa: E402

from match_charting_project.shots.notation import parse_point, stroke_kind  # noqa: E402

# Ordered feature columns (the fingerprint vector).
FEATURES = [
    "serve_wide", "serve_t",      # 1st-serve location lean (body = the remainder)
    "ace_rate", "df_rate",        # serve potency / risk
    "return_slice", "return_deep",  # return game: chip vs drive, depth
    "slice_pct", "net_pct",       # rally: slice reliance, net-forwardness
    "fh_share",                   # forehand reliance (runs around the backhand)
    "avg_rally_len",              # tempo
    # baseline (groundstroke) winners only -- net put-aways are captured by net_pct,
    # so this isolates ambitious shotmaking from easy volley/overhead finishes.
    "gs_winner_rate", "unforced_rate",
]


def _row(c: dict) -> dict:
    """Derive rate features from a player's raw counters."""
    pts = c["points"]
    serve1 = max(c["serve1_pts"], 1)
    serve = max(c["serve_pts"], 1)
    rets = max(c["returns"], 1)
    ret_d = max(c["returns_depth"], 1)
    rally = max(c["rally_shots"], 1)
    gs = max(c["fh_gs"] + c["bh_gs"], 1)
    return {
        "n_points": pts,
        "serve_wide": c["serve_4"] / serve1,
        "serve_t": c["serve_6"] / serve1,
        "ace_rate": c["aces"] / serve,
        "df_rate": c["dfs"] / serve,
        "return_slice": c["return_slice"] / rets,
        "return_deep": c["return_deep"] / ret_d,
        "slice_pct": c["slice_shots"] / rally,
        "net_pct": c["net_shots"] / rally,
        "fh_share": c["fh_gs"] / gs,
        "avg_rally_len": c["rally_len_sum"] / pts,
        "gs_winner_rate": c["gs_winners"] / pts,
        "unforced_rate": c["unforced"] / pts,
    }


def build_fingerprints(con, gender: str, min_points: int = 2000) -> pd.DataFrame:
    """One row per player (>= ``min_points``) with the FEATURES columns."""
    acc: dict = defaultdict(lambda: defaultdict(int))
    sql = (
        "SELECT m.player1, m.player2, p.svr, p.first_serve, p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for p1, p2, svr, fs, ss, win in batch:
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            names = {1: p1, 2: p2}
            srv, ret = names[pt.server], names[pt.returner]
            for who in (srv, ret):
                acc[who]["points"] += 1
                acc[who]["rally_len_sum"] += pt.rally_len
            acc[srv]["serve_pts"] += 1
            acc[ret]["return_pts"] += 1

            if pt.serve_in_play == 1 and pt.shots:
                acc[srv]["serve1_pts"] += 1
                acc[srv][f"serve_{pt.shots[0].direction}"] += 1
            if pt.outcome == "ace":
                acc[srv]["aces"] += 1
            elif pt.outcome == "double_fault":
                acc[srv]["dfs"] += 1
            elif pt.outcome == "winner" and pt.last_hitter:
                # count only groundstroke winners; volley/overhead put-aways belong
                # to the net game (net_pct), not to "ambitious" shotmaking.
                last = pt.shots[-1]
                if stroke_kind(last.letter, last.is_serve) in ("drive", "slice"):
                    acc[names[pt.last_hitter]]["gs_winners"] += 1
            elif pt.outcome == "unforced_error" and pt.last_hitter:
                acc[names[pt.last_hitter]]["unforced"] += 1

            # The return is the 2nd stroke, hit by the returner.
            if len(pt.shots) >= 2 and not pt.shots[1].is_serve:
                r = pt.shots[1]
                acc[ret]["returns"] += 1
                if r.letter in "rs":
                    acc[ret]["return_slice"] += 1
                if r.depth:
                    acc[ret]["returns_depth"] += 1
                    if r.depth == "9":
                        acc[ret]["return_deep"] += 1

            for s in pt.shots:
                if s.is_serve:
                    continue
                who = names[s.hitter]
                acc[who]["rally_shots"] += 1
                kind = stroke_kind(s.letter, False)
                if kind == "slice":
                    acc[who]["slice_shots"] += 1
                if kind == "net" or "+" in s.modifiers or "-" in s.modifiers:
                    acc[who]["net_shots"] += 1
                if kind in ("drive", "slice"):
                    acc[who]["fh_gs" if s.side == "FH" else "bh_gs"] += 1

    rows = []
    for player, c in acc.items():
        if c["points"] < min_points:
            continue
        row = {"player": player, "gender": gender}
        row.update(_row(c))
        rows.append(row)
    return pd.DataFrame(rows).set_index("player").sort_values("n_points", ascending=False)
