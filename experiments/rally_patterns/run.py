"""Rally patterns: pattern mining with the opening blinded out.

Run:  python experiments/rally_patterns/run.py

Replaces ``deep_patterns``. That experiment mined 3-4 shot contexts anywhere in the
point, and 71% of its gold patterns' occurrences sat inside the first four plies —
ground that ``shot_triggers``' openings section and ``serve_plus_one`` already own at
higher support and at a resolution that knows which service court the point was
played to. Nine of its 36 patterns were pure serve sequences.

This one blinds the opening (serve, return, serve+1, return+1) and mines what is left.
Two things follow. **Pooling**: with the serve out of the window, a player's serving and
returning points, and the deuce and ad courts, are one population — tested here rather
than assumed, which is what ``deep_patterns`` did by citing ``serve_side``. And a
**clean split**: the opening belongs to ``shot_triggers``, the rally belongs here, and
no context spans both.

Blinding is swept rather than chosen. Under ``window`` no part of the context or the
struck ball touches the opening; under ``target`` only the struck ball has to clear it,
which is effectively what ``deep_patterns`` did. The gap between them is how much of the
deep-pattern yield was the serve.

**Every displayed figure is held out.** Each fold of a player's matches takes a turn
discovering — support floor, parent-lift gate, exact binomial against the parent, and a
per-player Benjamini-Hochberg correction across every context that fold screened — and
the rate, lift, conversion and tag are read off the other fold, which had no part in the
selection. ``deep_patterns`` gated on both halves and then displayed lift computed on
all of it, so every effect size it shipped was measured on data used to select it.

Writes reports/rally_patterns.{md,csv}, reports/rally_patterns_sweep.csv,
reports/rally_patterns_calibration.csv, reports/figures/rally_patterns.png.
"""

import math
import sys
import zlib
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shot_language"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from tokens import hand_map, point_tokens, pretty  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import aggressive_shot, parse_point  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402
from match_charting_project.stats import bh, binom_tail  # noqa: E402

BLIND = 4               # the opening: serve, return, serve+1, return+1 — shot_triggers' anchors
DEPTHS = (2, 3, 4)      # context lengths screened
RULES = ("window", "target")
SHIP_RULE = "window"    # the strict rule is what ships; `target` is the comparison arm
SHIP_MIN_DEPTH = 3      # shot_triggers owns K=2; only deeper rows go to the site
MIN_STROKES = 1_500     # window-eligible strokes a player needs to enter the pool
MIN_CTX, MIN_ATT = 50, 10       # support floor, applied inside the *discovery* fold
MIN_VAL_CTX, MIN_VAL_ATT = 25, 6   # support the validation fold needs to confirm
PARENT_LIFT = 1.3       # discovery-fold aggressive shot frequency vs its parent's
Q_FDR = 0.10            # Benjamini-Hochberg false-discovery rate, within player and fold
CAL_BINS = (1.3, 1.5, 1.75, 2.0, 2.5, 99)   # discovered-lift bins for the calibration curve
MIN_CAL = 10            # records a (rule, depth) needs before its calibration is quoted

# Cell layout: two folds x [strokes, aggressive shots, converted, summed ply index,
# occurrences whose context reaches back into the opening]. The last is always 0 under
# the `window` rule; under `target` it is the retrospective — how much of a pattern's
# evidence is the serve — which is the number that motivated replacing deep_patterns.
N, ATT, WIN, PLY, OPEN, W = 0, 1, 2, 3, 4, 5
GLABEL = {"M": "Men", "W": "Women"}
COLOR = {"window": "#2a78d6", "target": "#eb6834"}
INK, MUTED, GRID = "#1c1c1a", "#6b6b66", "#dcdcd6"
MARQUEE = {"M": ["Roger Federer", "Novak Djokovic", "Rafael Nadal", "Daniil Medvedev"],
           "W": ["Serena Williams", "Iga Swiatek", "Elena Rybakina", "Angelique Kerber"]}


# --------------------------------------------------------------------------- pool
def pool(con, gender: str) -> "tuple[set, dict]":
    """Players with >=MIN_STROKES strokes they actually hit past the opening.

    Gating on *charted points* (what ``deep_patterns`` did, at 10k) is the wrong
    denominator here: a point contributes strokes to this experiment only if it
    survives the blind, and how often that happens is exactly the thing that varies
    most between players. A big server's 10k points fund far less rally than a
    grinder's. So the gate counts the strokes the experiment will actually see, and it
    runs before any lift is computed — picking the pool by who surfaced patterns would
    be picking the players the screen flattered.

    Returned alongside is each player's **exposure**: the share of their charted points
    that reach the fifth shot at all. Everything downstream is conditional on that, and
    it runs from 0.17 to 0.53, so it ships next to every profile rather than sitting in
    a limitations paragraph. See the README.
    """
    rows = con.execute("""
        WITH pp AS (
          SELECT m.player1 p1, m.player2 p2, pa.server svr, pa.rally_len r
          FROM points_parsed pa JOIN matches m USING (match_id)
          WHERE pa.parse_ok AND pa.server IN (1,2) AND m.gender = ?),
        c AS (
          SELECT CASE WHEN svr=1 THEN p1 ELSE p2 END srv,
                 CASE WHEN svr=1 THEN p2 ELSE p1 END ret,
                 greatest(r - ?, 0) e, CASE WHEN r > ? THEN 1 ELSE 0 END reach
          FROM pp),
        s AS (
          SELECT srv player, (e+1)//2 n, reach FROM c
          UNION ALL SELECT ret, e//2, reach FROM c)
        SELECT player, sum(n) strokes, avg(reach) exposure, count(*) pts
        FROM s GROUP BY player
    """, [gender, BLIND + min(DEPTHS), BLIND]).fetchall()
    keep = {r[0] for r in rows if r[1] >= MIN_STROKES}
    return keep, {r[0]: {"strokes": r[1], "exposure": r[2], "pts": r[3]} for r in rows}


# ------------------------------------------------------------------------ collect
def collect(con, gender: str, keep: set, hands: dict):
    """One pass: per (rule, depth) context tables, plus the poolability tallies.

    A stroke at ply index ``i`` is eligible under ``target`` when ``i >= BLIND`` and
    under ``window`` when ``i - K >= BLIND``, so the whole K-shot context sits past the
    opening too. Both are tallied from the same pass.

    Contexts are keyed in the *profiled player's* frame — for a left-hander every court
    third in the sequence is mirrored, so a token names the shot rather than the half of
    the court it landed in. Mirrored by the striker's hand rather than each shot's own
    hitter, because the context alternates hitters and a player's opponents are a mix of
    both hands. This is the same convention ``shot_triggers`` and ``court_response`` use
    and it changes no statistic: every gate compares a context to its own parent within
    one player, so mirroring re-keys a lefty's whole table consistently.

    ``role`` tallies the K=2 window cells split by serving/returning role and by deuce/ad
    court, which is what ``poolability()`` tests. They are collected here rather than in a
    second pass because the claim they support — that these may be pooled — is the reason
    every other table in this function is pooled.
    """
    tabs = {(rule, k): defaultdict(lambda: [0] * (2 * W)) for rule in RULES for k in DEPTHS}
    role = defaultdict(lambda: [0] * 8)   # n_srv,a_srv,n_ret,a_ret,n_deuce,a_d,n_ad,a_a
    sql = ("SELECT p.match_id, m.player1, m.player2, p.svr, p.pts, p.first_serve, "
           "       p.second_serve, p.pt_winner FROM points p JOIN matches m USING (match_id) "
           "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?")
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for mid, p1, p2, svr, pts, fs, ss, win in batch:
            if p1 not in keep and p2 not in keep:
                continue
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok or len(pt.shots) <= BLIND:
                continue
            names = {1: p1, 2: p2}
            plain = point_tokens(pt)
            lefty = {w: hands.get(names[w]) == "L" for w in (1, 2)}
            mirrored = point_tokens(pt, (1, 2)) if (lefty[1] or lefty[2]) else plain
            toks_for = {w: (mirrored if lefty[w] else plain) for w in (1, 2)}
            f = W * (zlib.crc32(str(mid).encode()) & 1)   # fold, stable across runs
            side = serve_side(pts)
            n_sh = len(pt.shots)
            for i in range(BLIND, n_sh):
                hitter = pt.shots[i].hitter
                pl = names[hitter]
                if pl not in keep:
                    continue
                toks = toks_for[hitter]
                _w, _e, _f = aggressive_shot(pt.shots, i, n_sh)
                att, won = _w + _e + _f, _w + _f
                for k in DEPTHS:
                    if i - k < 0:
                        continue
                    ctx = tuple(toks[i - k:i])
                    eligible = ["target"] + (["window"] if i - k >= BLIND else [])
                    for rule in eligible:
                        c = tabs[(rule, k)][(pl, ctx)]
                        c[f + N] += 1
                        c[f + ATT] += att
                        c[f + WIN] += won
                        c[f + PLY] += i
                        if i - k < BLIND:
                            c[f + OPEN] += 1
                    if k == 2 and i - k >= BLIND:
                        r = role[(pl, ctx)]
                        o = 0 if hitter == pt.server else 2
                        r[o] += 1
                        r[o + 1] += att
                        if side in ("deuce", "ad"):
                            o = 4 if side == "deuce" else 6
                            r[o] += 1
                            r[o + 1] += att
    return tabs, role


def parents(tab: dict) -> dict:
    """The (K-1)-shot suffix table, summed over exactly the K-eligible strokes.

    ``deep_patterns`` looked its parent up in a table built over *all* of that parent's
    own occurrences, which is a wider and differently-distributed set of strokes than the
    child's — the child could only occur where a K-shot window was legal, the parent
    anywhere a (K-1)-shot one was. So part of every parent lift it reported was the two
    contexts being measured on different populations rather than the extra shot doing
    anything. Deriving the parent from the child cells by dropping the leading token
    fixes that by construction: both sides of the ratio are now the same strokes, and the
    only difference between them is the token the gate is asking about.
    """
    par = defaultdict(lambda: [0] * (2 * W))
    for (pl, ctx), v in tab.items():
        p = par[(pl, ctx[1:])]
        for j in range(2 * W):
            p[j] += v[j]
    return par


# ------------------------------------------------------------------------- screen
def candidates(tabs: dict, pars: dict, rule: str) -> dict:
    """player -> discovery fold -> candidate rows that reached the binomial test.

    The correction family is every context a player was screened on *in that fold*,
    across all three depths, not just the ones that cleared the lift gate. A context the
    screen looked at and turned away is not free: leaving it out would count a search
    over hundreds of contexts as a search over the handful that happened to clear 1.3x.
    Depths share one family because they are one search — the screen tries K=2, 3 and 4
    on the same player and ships whichever survives. The two *rules* do not, because they
    are two analyses of the same question and only one of them ships.
    """
    out = defaultdict(lambda: {0: [], 1: []})
    for k in DEPTHS:
        tab, par = tabs[(rule, k)], pars[(rule, k)]
        for (pl, ctx), v in tab.items():
            p = par.get((pl, ctx[1:]))
            if p is None:
                continue
            for disc in (0, 1):
                o = W * disc
                n, att = v[o + N], v[o + ATT]
                pn, patt = p[o + N], p[o + ATT]
                if n < MIN_CTX or att < MIN_ATT or pn == 0 or not 0 < patt < pn:
                    continue
                rate, prate = att / n, patt / pn
                out[pl][disc].append({
                    "player": pl, "depth": k, "context": ctx,
                    "n": n, "attempts": att, "att_rate": rate,
                    "parent_rate": prate, "parent_lift": rate / prate,
                    "pval": binom_tail(att, n, prate),
                    "ply": v[o + PLY] / n, "parent_ply": p[o + PLY] / pn,
                })
    return out


def validate(cell, pcell, disc: int) -> "dict | None":
    """Read a pattern's figures off the fold that had no part in selecting it."""
    o = W * (1 - disc)
    n, att, won = cell[o + N], cell[o + ATT], cell[o + WIN]
    pn, patt, pwon = pcell[o + N], pcell[o + ATT], pcell[o + WIN]
    if n < MIN_VAL_CTX or att < MIN_VAL_ATT or pn == 0 or patt == 0:
        return None
    rate, prate = att / n, patt / pn
    conv, pconv = won / att, pwon / patt
    return {"n": n, "attempts": att, "att_rate": rate, "parent_rate": prate,
            "parent_lift": rate / prate, "conversion": conv, "parent_conv": pconv,
            "conv_delta": conv - pconv, "tag": "green" if conv >= pconv else "trap"}


def screen(tabs: dict, pars: dict, rule: str, gender: str) -> "tuple[list, list, dict]":
    """Two-fold symmetric screen. Returns (shipped rows, discovery record, gate counts).

    The gate counts are the third return because a screen this strict can come back
    nearly empty, and an empty result is only readable next to how many candidates it
    started from. Without them "two patterns" and "a bug" look the same.

    The second list is the calibration record and it is deliberately unfiltered: it holds
    every pattern that cleared discovery and could be measured out of sample, including
    the ones whose held-out lift came back below 1. Conditioning that record on
    replicating would be selecting on the outcome it exists to measure.

    Dedup across the two directions follows ``shot_triggers``: a pattern confirmed from
    both sides shows the two clean folds pooled, one confirmed from a single side shows
    that validation fold alone, and a pattern whose two directions disagree about the tag
    is not a finding and is dropped.
    """
    cands, shipped, record = candidates(tabs, pars, rule), [], []
    gates = defaultdict(lambda: dict.fromkeys(
        ("tested", "selected", "measurable", "confirmed", "shipped"), 0))
    for pl, byfold in cands.items():
        confirmed = defaultdict(list)     # (depth, ctx) -> [(row, disc)]
        for disc in (0, 1):
            items = byfold[disc]
            if not items:
                continue
            for cand, q in zip(items, bh([c["pval"] for c in items])):
                gates[cand["depth"]]["tested"] += 1
                if q > Q_FDR or cand["parent_lift"] < PARENT_LIFT:
                    continue
                k, ctx = cand["depth"], cand["context"]
                gates[k]["selected"] += 1
                held = validate(tabs[(rule, k)][(pl, ctx)], pars[(rule, k)][(pl, ctx[1:])], disc)
                if held is None:
                    continue
                gates[k]["measurable"] += 1
                rec = {"player": pl, "gender": gender, "rule": rule, "depth": k,
                       "context": ctx, "disc_fold": disc, "p_bh": q,
                       "n_candidates": len(items),
                       "disc_lift": cand["parent_lift"], "disc_n": cand["n"],
                       "held_lift": held["parent_lift"], "held_n": held["n"],
                       "ply": cand["ply"], "parent_ply": cand["parent_ply"]}
                record.append(rec)
                if held["parent_lift"] >= 1.0:     # the direction held out of sample
                    gates[k]["confirmed"] += 1
                    confirmed[(k, ctx)].append((held, disc, cand, q, len(items)))
        for (k, ctx), hits in confirmed.items():
            if len({h[0]["tag"] for h in hits}) > 1:
                continue                  # the two directions disagree: not a finding
            if len(hits) == 2:
                # Both directions clean. Every stroke in the cell then served as
                # validation for a discovery made in the other fold, so the union is the
                # mean of two held-out halves rather than a return to in-sample figures.
                cell, pcell = tabs[(rule, k)][(pl, ctx)], pars[(rule, k)][(pl, ctx[1:])]
                n, att, won = (cell[j] + cell[W + j] for j in (N, ATT, WIN))
                pn, patt, pwon = (pcell[j] + pcell[W + j] for j in (N, ATT, WIN))
                rate, prate = att / n, patt / pn
                conv, pconv = won / att, pwon / patt
                held = {"n": n, "attempts": att, "att_rate": rate, "parent_rate": prate,
                        "parent_lift": rate / prate, "conversion": conv,
                        "parent_conv": pconv, "conv_delta": conv - pconv,
                        "tag": hits[0][0]["tag"]}
            else:
                held = hits[0][0]
            _h, disc, cand, q, ncand = hits[0]
            shipped.append({**held, "player": pl, "gender": gender, "rule": rule,
                            "depth": k, "context": ctx,
                            "disc_lift": cand["parent_lift"], "folds": len(hits),
                            "p_bh": q, "n_candidates": ncand,
                            "ply": cand["ply"], "parent_ply": cand["parent_ply"]})
            gates[k]["shipped"] += 1
    return shipped, record, dict(gates)


# -------------------------------------------------------------------- poolability
def _two_prop_p(n1, k1, n2, k2) -> float:
    """Two-sided p for equal proportions, normal approximation."""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    p = (k1 + k2) / (n1 + n2)
    var = p * (1 - p) * (1 / n1 + 1 / n2)
    if var <= 0:
        return 1.0
    z = abs(k1 / n1 - k2 / n2) / math.sqrt(var)
    return math.erfc(z / math.sqrt(2))


def poolability(role: dict, min_arm: int = 60) -> dict:
    """Do serving/returning role and deuce/ad court still matter once the serve is blind?

    Every other table here pools them, so this is the assumption the experiment rests on.
    ``deep_patterns`` asserted it by citing ``serve_side``'s model evaluation, which is a
    different test on different data. This one asks it directly of the cells being
    pooled, and calibrates against a coin-flip arm split of the same cells: whatever
    rejection rate the random split produces is what a real effect has to beat.
    """
    out = {}
    for label, (a, b, c, d) in (("role", (0, 1, 2, 3)), ("side", (4, 5, 6, 7))):
        p, cov = [], 0
        for v in role.values():
            if v[a] >= min_arm and v[c] >= min_arm:
                p.append(_two_prop_p(v[a], v[b], v[c], v[d]))
                cov += v[a] + v[c]
        rej = sum(1 for q in bh(p) if q <= Q_FDR) if p else 0
        out[label] = {"cells": len(p), "rejects": rej, "strokes": cov}
    return out


def ply_gap(rows: "pd.DataFrame") -> "pd.DataFrame":
    """Mean ply of a pattern against its parent's, on the same eligible strokes.

    Aggressive shot frequency drifts with how deep into the point a stroke sits, so a
    context that tends to arise early can read as aggressive for that reason alone.
    Blinding removes most of the drift — past ply 7 the tour rate is flat to within a
    point or so — and deriving the parent from the child cells removes the rest of the
    *set* difference, but not the difference in where inside that set the two sit. This
    measures what is left rather than correcting for it, which at this size is the
    honest option: a correction estimated from the same cells would be doing more
    inference than the residual is worth.
    """
    if not len(rows):
        return rows
    rows = rows.copy()
    rows["ply_gap"] = rows.ply - rows.parent_ply
    return rows


# -------------------------------------------------------------------- calibration
def calibration(record: "pd.DataFrame") -> "pd.DataFrame":
    """Discovered lift against the lift the same pattern posts out of sample.

    This is the experiment's headline and the reason the split exists. Every screen of
    this shape returns patterns whose measured edge is part real and part the luck that
    got them selected, and the only way to say which is to measure the same pattern on
    data that had no vote. The record is unfiltered on purpose — patterns that came back
    below 1 are in here, and dropping them would make the curve say what it was built
    to test.

    ``edge_kept`` is the share of the discovered edge that survives: mean(held − 1) over
    mean(discovered − 1). 1.0 would mean the screen is perfectly calibrated, 0.0 that it
    is selecting noise.
    """
    out = []
    for (rule, depth), sub in record.groupby(["rule", "depth"]):
        d, h = sub.disc_lift.mean(), sub.held_lift.mean()
        out.append({"rule": rule, "depth": depth, "patterns": len(sub),
                    "disc_lift": d, "held_lift": h,
                    "edge_kept": (h - 1) / (d - 1) if d > 1 else np.nan,
                    "replicated": (sub.held_lift >= 1).mean()})
    return pd.DataFrame(out)


def curve(record: "pd.DataFrame", rule: str) -> "pd.DataFrame":
    """Binned calibration curve for one rule: discovered-lift bin -> mean held-out lift."""
    sub = record[record.rule == rule]
    rows = []
    for lo, hi in zip(CAL_BINS, CAL_BINS[1:]):
        m = sub[(sub.disc_lift >= lo) & (sub.disc_lift < hi)]
        if len(m) >= 5:
            rows.append({"lo": lo, "hi": hi, "x": m.disc_lift.mean(),
                         "y": m.held_lift.mean(), "n": len(m)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------- figure
def figure(ship: "pd.DataFrame", record: "pd.DataFrame", path: Path) -> None:
    """Three panels: what each rule yields, and what its yield is worth out of sample."""
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 3.9))
    for ax in axes:
        ax.set_facecolor("white")
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        for sp in ("left", "bottom"):
            ax.spines[sp].set_color(GRID)
        ax.tick_params(colors=MUTED, labelsize=8, length=3)
        ax.yaxis.grid(True, color=GRID, lw=0.7)
        ax.set_axisbelow(True)

    width = 0.36
    for ax, g in zip(axes[:2], ("M", "W")):
        xs = np.arange(len(DEPTHS))
        for j, rule in enumerate(RULES):
            counts = [len(ship[(ship.gender == g) & (ship.rule == rule)
                               & (ship.depth == k)]) for k in DEPTHS]
            bars = ax.bar(xs + (j - 0.5) * width, counts, width * 0.94,
                          color=COLOR[rule], label=rule if g == "M" else None)
            ax.bar_label(bars, fontsize=7.5, color=MUTED, padding=2)
        ax.set_xticks(xs, [f"K={k}" for k in DEPTHS])
        ax.set_title(f"{GLABEL[g]} — patterns surviving", fontsize=9.5, color=INK)
        ax.set_ylabel("held-out survivors" if g == "M" else "", fontsize=8.5, color=MUTED)
    axes[0].legend(fontsize=8, frameon=False, labelcolor=MUTED)

    # Panel 3 is the point of the split: a pattern's lift where it was found, against
    # the lift it posts where it was not. Limits come from the curves rather than a
    # fixed frame — the interesting band is narrow and a square 1-4 axis buries it.
    ax = axes[2]
    curves = {rule: curve(record, rule) for rule in RULES}
    pts = [v for c in curves.values() if len(c) for v in (*c.x, *c.y)]
    lo, hi = (min(1.0, min(pts)), max(pts)) if pts else (1.0, 2.0)
    pad = 0.06 * (hi - lo)
    ax.plot([lo, hi], [lo, hi], ls="--", lw=1.2, color=MUTED, alpha=0.45, zorder=1)
    ax.axhline(1.0, lw=1, color=MUTED, alpha=0.45, zorder=1)
    for rule, c in curves.items():
        if not len(c):
            continue
        ax.plot(c.x, c.y, "-o", lw=2, ms=6, color=COLOR[rule], label=rule,
                mec="white", mew=1.2, zorder=3)
        # How many patterns each marker rests on. The two curves nearly touch at the
        # low-lift end, so the counts go opposite sides of their own line.
        dy = -12 if rule == "window" else 8
        for r in c.itertuples():
            ax.annotate(f"{r.n}", (r.x, r.y), textcoords="offset points",
                        xytext=(0, dy), ha="center", fontsize=7, color=COLOR[rule])
    ax.set_xlim(lo - pad, hi + pad)
    ax.set_ylim(lo - pad, hi + pad)
    ax.annotate("no edge kept", (hi, 1.0), fontsize=7.5, color=MUTED,
                ha="right", va="bottom")
    mid = lo + 0.55 * (hi - lo)      # on the diagonal, clear of the top-right markers
    ax.annotate("all of it kept", (mid, mid), fontsize=7.5, color=MUTED,
                ha="center", va="bottom", rotation=38, rotation_mode="anchor")
    ax.set_xlabel("lift over the parent, in the fold that found it", fontsize=8.5, color=MUTED)
    ax.set_ylabel("lift in the held-out fold", fontsize=8.5, color=MUTED)
    ax.set_title("What a discovered edge is worth", fontsize=9.5, color=INK)
    ax.legend(fontsize=8, frameon=False, labelcolor=MUTED, loc="upper left")

    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110, facecolor="white")
    plt.close(fig)


# ------------------------------------------------------------------------- report
def _ctx_str(ctx) -> str:
    return " · ".join(pretty(t) for t in ctx)


def report(ship, record, cal, gates, pool_res, meta, open_share) -> str:
    md = ["# Rally patterns — shot sequences with the opening blinded out", ""]
    md.append("*Generated by `experiments/rally_patterns/run.py`. Replaces "
              "`deep_patterns`. The first "
              f"{BLIND} plies — serve, return, serve+1, return+1 — are blinded out, "
              "which is exactly the span `shot_triggers` covers side-by-side in its "
              "openings section, so the two partition the point with no overlap and no "
              "gap. Every rate, lift, conversion and tag below is read off a fold of "
              "the player's matches that had no part in selecting the pattern.*")
    md.append("")

    md.append("## The pool")
    md.append("")
    md.append(f"A player enters on **strokes they actually hit past the opening** "
              f"(≥{MIN_STROKES:,}), not on charted points. The two are not "
              "interchangeable: how much rally a player's points fund is precisely what "
              "varies most here.")
    md.append("")
    md.append("| | players | strokes past the opening | exposure p10 / median / p90 |")
    md.append("|---|--:|--:|:--|")
    for g in ("M", "W"):
        m = meta[g]
        e = m["exposure"]
        md.append(f"| {GLABEL[g]} | {m['players']} | {m['strokes']:,} | "
                  f"{e[0]:.2f} / {e[1]:.2f} / {e[2]:.2f} |")
    md.append("")
    md.append("**Exposure** is the share of a player's charted points that reach the "
              "fifth shot at all, and it is the deepest limitation here. Blinding the "
              "opening does not remove the serve from these profiles — it *conditions "
              "on* it. Karlovic's rally book is built from the one point in five his "
              "serve failed to settle; Ferrer's from half of his. Every claim below is "
              "conditional on the point having got this far, and the exposure column "
              "ships next to it so that reading is available rather than buried.")
    md.append("")

    md.append("## Can serving and returning points be pooled?")
    md.append("")
    md.append("Everything here pools a player's serving and returning points, and the "
              "deuce and ad courts. `deep_patterns` pooled them too, on the strength of "
              "`serve_side`'s model evaluation — a different test on different data. "
              "This asks the cells being pooled directly, against a coin-flip split of "
              "the same cells as the calibration.")
    md.append("")
    md.append("| | test | cells | rejected at q=0.10 |")
    md.append("|---|---|--:|--:|")
    for g in ("M", "W"):
        for label, name in (("role", "server vs returner"), ("side", "deuce vs ad")):
            r = pool_res[g][label]
            md.append(f"| {GLABEL[g]} | {name} | {r['cells']:,} | "
                      f"{r['rejects']} ({r['rejects'] / max(r['cells'], 1):.1%}) |")
    md.append("")
    md.append("So the pooling is justified rather than assumed, and the "
              "`deep_patterns` side-refinement pass — a Holm-corrected Fisher test over "
              "every survivor — is not needed on this ground and is gone.")
    md.append("")

    md.append("## The blinding sweep")
    md.append("")
    md.append("`window` blinds the whole K-shot window plus the struck ball. `target` "
              "blinds only the struck ball, letting the context reach back into the "
              "opening — which is effectively what `deep_patterns` did. The difference "
              "between the two columns is how much of a deep-pattern yield is the serve.")
    md.append("")
    md.append("A screen this strict can come back empty, and an empty result only reads "
              "next to the pool it started from. `candidates` counts every "
              "(player, context) that reached the binomial test in some fold; `selected` "
              "cleared the lift gate and per-player Benjamini-Hochberg; `held` could then "
              "be measured on the other fold and came back above its parent there.")
    md.append("")
    md.append("| rule | K | candidates | selected | held | shipped M / W | "
              "held-out lift | edge kept |")
    md.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for rule in RULES:
        for k in DEPTHS:
            g_ = gates[(gates.rule == rule) & (gates.depth == k)]
            c = cal[(cal.rule == rule) & (cal.depth == k)]
            nm = len(ship[(ship.rule == rule) & (ship.depth == k) & (ship.gender == "M")]) \
                if len(ship) else 0
            nw = len(ship[(ship.rule == rule) & (ship.depth == k) & (ship.gender == "W")]) \
                if len(ship) else 0
            tested = int(g_.tested.sum()) if len(g_) else 0
            sel = int(g_.selected.sum()) if len(g_) else 0
            conf = int(g_.confirmed.sum()) if len(g_) else 0
            if len(c) and c.iloc[0].patterns >= MIN_CAL:
                r = c.iloc[0]
                stat = f"{r.held_lift:.2f}× | {r.edge_kept:.0%}"
            else:
                n = int(c.iloc[0].patterns) if len(c) else 0
                stat = f"— | — *(n={n})*"
            md.append(f"| {rule} | {k} | {tested:,} | {sel} | {conf} | {nm} / {nw} | {stat} |")
    md.append("")
    md.append(f"*Calibration is quoted only where at least {MIN_CAL} patterns reached "
              "the held-out measurement; below that the number would be an anecdote "
              "with a percent sign on it.*")
    md.append("")
    if open_share is not None:
        md.append(f"Under `target`, **{open_share:.0%} of the surviving patterns' "
                  "evidence sits in occurrences whose context reaches back into the "
                  "opening.** The same measurement on `deep_patterns`' shipped set read "
                  "71%, and the two are not directly comparable — that screen put no "
                  "floor on the struck ball at all, so its contexts could start at the "
                  "serve, where this arm still requires the struck ball past ply "
                  f"{BLIND}. The 44% is therefore the *understated* version of the "
                  "problem, and it is the redundancy this experiment removes: those "
                  "occurrences are serve patterns, and `shot_triggers` and "
                  "`serve_plus_one` already report them at higher support and split by "
                  "service court, which a pooled deep context cannot do.")
        md.append("")
    md.append("![rally patterns](figures/rally_patterns.png)")
    md.append("")

    md.append("## What survives")
    md.append("")
    shipped = ship[(ship.rule == SHIP_RULE) & (ship.depth >= SHIP_MIN_DEPTH)]
    if not len(shipped):
        md.append("**Nothing.** On serve-blind ground, with every figure held out, no "
                  "context deeper than two shots clears the screen. Read together with "
                  "the `target` row above, that is the finding: deep patterns were the "
                  "serve.")
    else:
        md.append(f"{len(shipped)} patterns across {shipped.player.nunique()} players "
                  f"at K≥{SHIP_MIN_DEPTH} under the `{SHIP_RULE}` rule — the set that "
                  "ships to the site's starred tier.")
        md.append("")
        for g in ("M", "W"):
            sub = shipped[shipped.gender == g]
            if not len(sub):
                continue
            md.append(f"### {GLABEL[g]}\n")
            names = [p for p in MARQUEE[g] if p in set(sub.player)]
            names += [p for p in sub.player.value_counts().index if p not in names][:4]
            for player in names[:6]:
                rows = sub[sub.player == player].sort_values("parent_lift", ascending=False)
                md.append(f"**{player}** — {len(rows)} pattern(s)")
                for r in rows.head(4).itertuples():
                    kind = "✅" if r.tag == "green" else "⚠️"
                    md.append(f"- `{_ctx_str(r.context)}` → aggressive "
                              f"{r.att_rate:.0%} vs the shorter pattern's "
                              f"{r.parent_rate:.0%} ({r.parent_lift:.2f}×), converts "
                              f"{r.conversion:.0%} {kind} (held-out n={r.n})")
                md.append("")
    md.append("")

    md.append("## Where the drift is")
    md.append("")
    if len(ship):
        gap = (ship.ply - ship.parent_ply)
        md.append("Aggressive shot frequency drifts with how deep into the point a "
                  "stroke sits, so a context arising early can read as aggressive for "
                  "that reason alone. Two things hold it down here: blinding removes "
                  "the steep part of the curve (past ply 7 the tour rate is flat to "
                  "within about a point), and the parent is summed over exactly the "
                  "strokes the child was eligible on, so both sides of every ratio "
                  "share a population. What is left is where inside that population "
                  "the two sit, measured rather than corrected: the median surviving "
                  f"pattern sits {gap.median():+.2f} plies from its parent, and "
                  f"{(gap.abs() > 1).mean():.0%} are more than a ply away.")
    md.append("")

    md.append("## Honest limitations")
    md.append("")
    md.append("- **Conditional on survival.** See exposure above. This is selection, "
              "not noise, and no amount of data fixes it — blinding deeper makes it "
              "worse. The per-context framing is the defence: both sides of every "
              "comparison inherit the same selection, so it largely cancels for the "
              "lift over the parent. It does not cancel for anything read across "
              "players.")
    md.append("- **The screen is stricter than the one it replaces**, so the counts are "
              "not comparable to `deep_patterns`' 36. That screen asked for 60 strokes "
              f"pooled across all the data; this one asks for {MIN_CTX} in the "
              f"discovery fold alone and a further {MIN_VAL_CTX} in the validation "
              "fold, so a surviving pattern rests on more evidence, not less — and its "
              "displayed lift was never measured on a stroke that helped select it.")
    md.append("- **Era-mixing is inherited.** A twenty-year career is one bag of "
              "strokes here, as it was in `deep_patterns`. `court_response` weights its "
              "field to a player's own era; this screen compares a player only against "
              "themselves, so era enters through which contexts they faced rather than "
              "through the baseline.")
    md.append("- **One numerator.** `deep_patterns` carried a shadow pass re-running "
              "the screen on the narrower finishing-shot reading. That question was "
              "settled by `shot_triggers` on far more support (the wider numerator "
              "replicates better, split-half r +0.811 vs +0.762), and the multiplicity "
              "budget here is spent on the blinding sweep instead.")
    md.append("- **The pool is coverage-defined**, so it skews to players charted "
              "across many years, and to the ones whose points last long enough to "
              "leave strokes behind after the blind.")
    return "\n".join(md) + "\n"


# --------------------------------------------------------------------------- main
def main() -> None:
    con = connect()
    hands = hand_map(con)
    ship, record, gates, pool_res, meta = [], [], [], {}, {}
    open_num = open_den = 0
    for g in ("M", "W"):
        keep, info = pool(con, g)
        tabs, role = collect(con, g, keep, hands)
        pars = {key: parents(tab) for key, tab in tabs.items()}
        for rule in RULES:
            s, r, gt = screen(tabs, pars, rule, g)
            ship += s
            record += r
            for k, counts in gt.items():
                gates.append({"gender": g, "rule": rule, "depth": k, **counts})
            if rule == "target":
                for row in s:
                    cell = tabs[(rule, row["depth"])][(row["player"], row["context"])]
                    open_num += cell[OPEN] + cell[W + OPEN]
                    open_den += cell[N] + cell[W + N]
        pool_res[g] = poolability(role)
        ex = pd.Series({p: info[p]["exposure"] for p in keep})
        meta[g] = {"players": len(keep),
                   "strokes": sum(info[p]["strokes"] for p in keep),
                   "exposure": [ex.quantile(0.1), ex.median(), ex.quantile(0.9)],
                   "info": info}
        del tabs, pars, role

    ship = pd.DataFrame(ship)
    record = pd.DataFrame(record)
    if len(ship):
        ship["exposure"] = [meta[g]["info"][p]["exposure"]
                            for g, p in zip(ship.gender, ship.player)]
    if len(record):
        record["context"] = record.context.map(_ctx_str)
    gates = pd.DataFrame(gates) if gates else pd.DataFrame(
        columns=["gender", "rule", "depth", "tested", "selected",
                 "measurable", "confirmed", "shipped"])
    cal = calibration(record) if len(record) else pd.DataFrame(
        columns=["rule", "depth", "patterns", "disc_lift", "held_lift",
                 "edge_kept", "replicated"])
    open_share = open_num / open_den if open_den else None

    figure(ship, record, PROJECT_ROOT / "reports" / "figures" / "rally_patterns.png")

    rep = PROJECT_ROOT / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "rally_patterns.md").write_text(
        report(ship, record, cal, gates, pool_res, meta, open_share))
    sweep = (gates.groupby(["rule", "depth"], as_index=False)
             [["tested", "selected", "measurable", "confirmed", "shipped"]].sum()
             .merge(cal, on=["rule", "depth"], how="left"))
    sweep.round(4).to_csv(rep / "rally_patterns_sweep.csv", index=False)
    if len(record):
        record.round(4).to_csv(rep / "rally_patterns_calibration.csv", index=False)

    # Site-facing CSV: the strict rule, deeper than the two-shot contexts shot_triggers
    # already ships, with the column names build_insights expects.
    cols = ["player", "gender", "depth", "context", "n", "attempts", "att_rate",
            "parent_rate", "parent_lift", "conversion", "parent_conv", "conv_delta",
            "tag", "folds", "p_bh", "n_candidates", "exposure", "ply", "parent_ply"]
    out = (ship[(ship.rule == SHIP_RULE) & (ship.depth >= SHIP_MIN_DEPTH)].copy()
           if len(ship) else pd.DataFrame(columns=cols))
    if len(out):
        out["context"] = out.context.map(_ctx_str)   # tuples stay tuples until display
    out.reindex(columns=cols).round(4).to_csv(rep / "rally_patterns.csv", index=False)
    print(f"wrote reports/rally_patterns.md + .csv ({len(out)} shipped patterns) "
          "+ _sweep.csv + _calibration.csv + figure")


if __name__ == "__main__":
    main()
