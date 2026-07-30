"""Per-*performance* feature vectors: one row per (match, player), names stripped.

Every other analysis in this repo aggregates a player over their whole career (or a
career era) and asks what they are like. This asks the opposite question: treat a
single player's showing in a single match as the unit, throw the name away, and see
whether the vector still points back at the human who produced it.

Three blocks, kept separate on purpose, because the interesting question is how much
work each one does:

``SERVE``   the delivery — direction by court side, first-serve rate, ace/DF/unreturned.
            The obvious tell, and the one to quarantine.
``RETURN``  the return of serve: slice vs drive, depth, direction, error rate.
``RALLY``   strokes 3+ — the shot mix that comes back at you once the point is live.

RETURN + RALLY together are ``RESPONSE``: everything you could observe from the far
baseline without watching the opponent serve.

Two conventions matter for the controls to mean anything:

- **Rates are conditioned on charted denominators.** Depth shares are computed over
  returns whose depth was charted, direction shares over strokes with a charted
  direction. Charters vary in how much detail they record, so an unconditioned rate
  would partly measure the charter rather than the player — the exact confound the
  experiment has to rule out rather than absorb.
- **No feature uses the opponent's name, the score, or the match context.** Surface,
  year, charter and opponent are carried alongside as metadata so pairs can be
  filtered by them later, never as inputs.

Caveat inherited from ``player_styles``: a player's shots are partly reactive, so a
performance vector is "what they did against this opponent on this day", not an
intrinsic constant. That is the whole point here — the question is how much of it
survives the change of opponent.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd  # noqa: E402

from match_charting_project.shots.notation import parse_point, stroke_kind  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402

SERVE_FEATURES = [
    "sv_deuce_wide", "sv_deuce_t",   # 1st-serve direction, deuce court (body = remainder)
    "sv_ad_wide", "sv_ad_t",         # 1st-serve direction, ad court
    "sv2_wide", "sv2_t",             # 2nd-serve direction lean
    "sv_first_in",                   # 1st serves landed / service points
    "sv_ace", "sv_df", "sv_unret",   # potency and risk
]
RETURN_FEATURES = [
    "ret_in",                        # returns made / return points faced
    "ret_slice",                     # chip/slice vs drive
    "ret_deep", "ret_shallow",       # depth mix, among returns with charted depth
    "ret_dir1", "ret_dir3",          # direction mix, among returns with charted direction
    "ret_fh",                        # wing the return came off
]
RALLY_FEATURES = [
    "ral_fh",                        # forehand share of groundstrokes
    "ral_slice", "ral_net",          # slice reliance, net strokes
    "ral_dir1", "ral_dir3",          # direction mix, among strokes with charted direction
    "ral_winner", "ral_unforced", "ral_forced",   # how their points end, per own stroke
    "net_point_rate",                # points where they came forward at all
    "shots_per_point",              # own strokes per point — tempo they impose
    "avg_rally_len",                 # match tempo (shared with the opponent; see README)
]
RESPONSE_FEATURES = RETURN_FEATURES + RALLY_FEATURES
ALL_FEATURES = SERVE_FEATURES + RESPONSE_FEATURES

BLOCKS = {
    "serve": SERVE_FEATURES,
    "return": RETURN_FEATURES,
    "rally": RALLY_FEATURES,
    "response": RESPONSE_FEATURES,
    "all": ALL_FEATURES,
}

# Per-performance minimums. A rate from 8 service points is mostly sampling noise;
# these keep every block on the same rows so the block comparison is apples-to-apples.
MIN_SERVE_PTS = 30
MIN_RETURNS = 25
MIN_RALLY_SHOTS = 40

_META = ["player", "opponent", "gender", "hand", "opp_hand", "charted_by",
         "surface", "year", "tier", "round"]


def _rates(c: dict) -> dict:
    """Turn one performance's raw counters into the rate features."""
    d = max(c["sv1_deuce"], 1)
    a = max(c["sv1_ad"], 1)
    s2 = max(c["sv2"], 1)
    sp = max(c["serve_pts"], 1)
    rp = max(c["return_pts"], 1)
    rets = max(c["returns"], 1)
    rdep = max(c["ret_depth_charted"], 1)
    rdir = max(c["ret_dir_charted"], 1)
    ral = max(c["rally_shots"], 1)
    gs = max(c["ral_fh_gs"] + c["ral_bh_gs"], 1)
    aldir = max(c["ral_dir_charted"], 1)
    pts = max(c["points"], 1)
    return {
        # serve
        "sv_deuce_wide": c["sv1_deuce_4"] / d,
        "sv_deuce_t": c["sv1_deuce_6"] / d,
        "sv_ad_wide": c["sv1_ad_4"] / a,
        "sv_ad_t": c["sv1_ad_6"] / a,
        "sv2_wide": c["sv2_4"] / s2,
        "sv2_t": c["sv2_6"] / s2,
        "sv_first_in": c["first_in"] / sp,
        "sv_ace": c["aces"] / sp,
        "sv_df": c["dfs"] / sp,
        "sv_unret": c["unreturned"] / sp,
        # return
        "ret_in": c["returns"] / rp,
        "ret_slice": c["ret_slice"] / rets,
        "ret_deep": c["ret_deep"] / rdep,
        "ret_shallow": c["ret_shallow"] / rdep,
        "ret_dir1": c["ret_dir_1"] / rdir,
        "ret_dir3": c["ret_dir_3"] / rdir,
        "ret_fh": c["ret_fh"] / rets,
        # rally
        "ral_fh": c["ral_fh_gs"] / gs,
        "ral_slice": c["ral_slice"] / ral,
        "ral_net": c["ral_net"] / ral,
        "ral_dir1": c["ral_dir_1"] / aldir,
        "ral_dir3": c["ral_dir_3"] / aldir,
        "ral_winner": c["winners"] / ral,
        "ral_unforced": c["unforced"] / ral,
        "ral_forced": c["forced"] / ral,
        "net_point_rate": c["net_points"] / pts,
        "shots_per_point": c["own_shots"] / pts,
        "avg_rally_len": c["rally_len_sum"] / pts,
    }


_SQL = """
SELECT p.match_id, p.svr, p.pts, p.first_serve, p.second_serve, p.pt_winner,
       m.player1, m.player2, m.player1_hand, m.player2_hand, m.gender,
       m.charted_by, m.surface_clean, m.year, m.tier, m.round
FROM points p JOIN matches m USING (match_id)
WHERE p.svr IN (1, 2) AND p.pt_winner IN (1, 2)
"""


def _hand(raw) -> str:
    """Handedness, defensively — the column carries a handful of stray datestamps."""
    h = (raw or "").strip().upper()
    return h if h in ("R", "L") else "?"


def build_performances(con, batch_size: int = 200_000) -> pd.DataFrame:
    """One row per (match_id, slot) performance meeting the minimum-volume cuts.

    ``slot`` is 1 or 2 (the match's player1/player2). The player name rides along as
    metadata for scoring only — nothing downstream of the metric ever reads it.
    """
    acc: dict = defaultdict(lambda: defaultdict(int))
    meta: dict = {}
    cur = con.execute(_SQL)
    while True:
        batch = cur.fetchmany(batch_size)
        if not batch:
            break
        for (mid, svr, pts_str, fs, ss, win, p1, p2, h1, h2, gender,
             charter, surface, year, tier, rnd) in batch:
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            srv, ret = pt.server, pt.returner
            if (mid, srv) not in meta:
                for slot, (me, opp, mh, oh) in {1: (p1, p2, h1, h2),
                                               2: (p2, p1, h2, h1)}.items():
                    meta[(mid, slot)] = {
                        "player": me, "opponent": opp, "gender": gender,
                        "hand": _hand(mh), "opp_hand": _hand(oh),
                        "charted_by": charter or "?", "surface": surface or "?",
                        "year": year, "tier": tier or "?", "round": rnd or "?",
                    }
            cs, cr = acc[(mid, srv)], acc[(mid, ret)]
            cs["points"] += 1
            cr["points"] += 1
            cs["rally_len_sum"] += pt.rally_len
            cr["rally_len_sum"] += pt.rally_len
            cs["serve_pts"] += 1
            cr["return_pts"] += 1

            # --- serve: direction by court side, first-serve rate, potency ---
            side = serve_side(pts_str)
            first = pt.serve_in_play == 1
            if first:
                cs["first_in"] += 1
            if pt.shots and pt.shots[0].is_serve:
                dirn = pt.shots[0].direction
                if first and side in ("deuce", "ad"):
                    cs[f"sv1_{side}"] += 1
                    if dirn in ("4", "6"):
                        cs[f"sv1_{side}_{dirn}"] += 1
                elif not first:
                    cs["sv2"] += 1
                    if dirn in ("4", "6"):
                        cs[f"sv2_{dirn}"] += 1
            if pt.outcome == "ace":
                cs["aces"] += 1
                cs["unreturned"] += 1
            elif pt.outcome == "double_fault":
                cs["dfs"] += 1
            elif pt.rally_len == 2 and pt.last_hitter == ret and pt.server_won:
                cs["unreturned"] += 1          # served, return missed

            # --- return: the 2nd stroke, hit by the returner ---
            if len(pt.shots) >= 2 and not pt.shots[1].is_serve:
                r = pt.shots[1]
                cr["returns"] += 1
                if stroke_kind(r.letter, False) == "slice":
                    cr["ret_slice"] += 1
                if r.side == "FH":
                    cr["ret_fh"] += 1
                if r.depth in ("7", "8", "9"):
                    cr["ret_depth_charted"] += 1
                    if r.depth == "9":
                        cr["ret_deep"] += 1
                    elif r.depth == "7":
                        cr["ret_shallow"] += 1
                if r.direction in ("1", "2", "3"):
                    cr["ret_dir_charted"] += 1
                    cr[f"ret_dir_{r.direction}"] += 1

            # --- rally: strokes 3+ (the ball coming back once the point is live) ---
            came_forward = set()
            for s in pt.shots:
                if s.is_serve:
                    continue
                c = acc[(mid, s.hitter)]
                c["own_shots"] += 1
                kind = stroke_kind(s.letter, False)
                at_net = kind == "net" or "+" in s.modifiers or "-" in s.modifiers
                if at_net:
                    came_forward.add(s.hitter)
                if s.idx < 3:
                    continue                    # the return is its own block
                c["rally_shots"] += 1
                if kind == "slice":
                    c["ral_slice"] += 1
                if at_net:
                    c["ral_net"] += 1
                if kind in ("drive", "slice"):
                    c["ral_fh_gs" if s.side == "FH" else "ral_bh_gs"] += 1
                if s.direction in ("1", "2", "3"):
                    c["ral_dir_charted"] += 1
                    c[f"ral_dir_{s.direction}"] += 1
            for who in came_forward:
                acc[(mid, who)]["net_points"] += 1

            # Terminal credit: attach the ending to whoever hit the last stroke, but
            # only for live rallies (aces / double faults are the serve's business).
            if pt.last_hitter and pt.rally_len >= 3:
                key = {"winner": "winners", "unforced_error": "unforced",
                       "forced_error": "forced"}.get(pt.outcome)
                if key:
                    acc[(mid, pt.last_hitter)][key] += 1

    rows = []
    for (mid, slot), c in acc.items():
        if (c["serve_pts"] < MIN_SERVE_PTS or c["returns"] < MIN_RETURNS
                or c["rally_shots"] < MIN_RALLY_SHOTS):
            continue
        row = {"match_id": mid, "slot": slot}
        row.update(meta[(mid, slot)])
        row.update(_rates(c))
        row["n_points"] = c["points"]
        row["n_serve_pts"] = c["serve_pts"]
        row["n_rally_shots"] = c["rally_shots"]
        rows.append(row)
    df = pd.DataFrame(rows)
    return df[["match_id", "slot", *_META, "n_points", "n_serve_pts",
               "n_rally_shots", *ALL_FEATURES]]


def load_performances(con, cache: "Path | None" = None,
                      refresh: bool = False) -> pd.DataFrame:
    """``build_performances`` with a parquet cache (the parse is a few minutes)."""
    if cache and cache.exists() and not refresh:
        return pd.read_parquet(cache)
    df = build_performances(con)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache, index=False)
    return df


__all__ = ["BLOCKS", "ALL_FEATURES", "SERVE_FEATURES", "RETURN_FEATURES",
           "RALLY_FEATURES", "RESPONSE_FEATURES", "build_performances",
           "load_performances"]
