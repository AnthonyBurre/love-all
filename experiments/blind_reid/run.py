"""End-to-end: strip the names, score blind re-identification, report.

Run:  python experiments/blind_reid/run.py [--refresh]

Produces:
  reports/blind_reid.md                          the findings
  reports/blind_reid_blocks.csv                  AUC / rank-1 per feature block
  reports/blind_reid_features.csv                per-feature identity signal
  reports/blind_reid_players.csv                 per-player self-consistency
  reports/figures/blind_reid_blocks.png          which block carries identity
  reports/figures/blind_reid_controls.png        does the signal survive the confounds
  reports/figures/blind_reid_distances.png       same-player vs different-player
  reports/figures/blind_reid_size.png            accuracy vs how long the match was
  reports/figures/blind_reid_drift.png           self-similarity vs years apart
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from features import ALL_FEATURES, BLOCKS, SERVE_FEATURES, load_performances  # noqa: E402
from reid import (  # noqa: E402
    apply_metric,
    auc_on,
    confusable_pairs,
    distances,
    fit_metric,
    pair_dists,
    pair_index,
    rank1,
    relabel,
    self_vs_other,
    split_players,
)

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402

FIG_DIR = PROJECT_ROOT / "reports" / "figures"
CACHE = PROJECT_ROOT / "data" / "processed" / "blind_reid_performances.parquet"
GLABEL = {"M": "men", "W": "women"}

# Categorical slots 1-2 of the validated default palette (validate_palette.js:
# all checks pass, worst adjacent CVD dE 24.7). Colour tracks the entity (the tour),
# fixed order, never recycled; text stays in ink colours throughout.
COLOR = {"M": "#2a78d6", "W": "#eb6834"}
INK, MUTED, GRID = "#1c1c1a", "#6b6b66", "#dcdcd6"

# Per-player performance cap. Uncapped, Federer's 700+ charted matches alone would
# supply ~23% of every same-player pair in the men's draw, so the headline AUC would
# mostly be a statement about one player. Capping makes it a statement about the tour.
PER_PLAYER_CAP = 30
MIN_PERF_FOR_PLAYER_STATS = 6
BLOCK_ORDER = ["serve", "return", "rally", "response", "all"]


def _style(ax, title="", xlabel="", ylabel=""):
    ax.set_title(title, color=INK, fontsize=10, pad=8)
    ax.set_xlabel(xlabel, color=MUTED, fontsize=8)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=8)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.set_axisbelow(True)
    ax.grid(axis="y", color=GRID, linewidth=0.6)


def _label_ends(ax, series: "dict[str, list]", x0: int = 0,
                fmt: str = "{:.3f}") -> None:
    """Direct-label the first and last point of each tour's line.

    Endpoints only (the axis carries the middle), and each label goes on the side its
    own series is on, so where the two lines nearly touch the labels don't collide.
    ``x0`` is the x value of index 0.
    """
    for g, ys in series.items():
        other = next(k for k in series if k != g)
        for k in (0, len(ys) - 1):
            above = ys[k] >= series[other][k]
            ax.annotate(fmt.format(ys[k]), (x0 + k, ys[k]),
                        xytext=(0, 8 if above else -14), textcoords="offset points",
                        ha="center", fontsize=7, color=INK)


def prepare(df: pd.DataFrame, gender: str, seed: int = 7) -> pd.DataFrame:
    """One gender, capped per player. Style spaces differ, so the tours never mix —
    and cross-gender pairs would be trivially separable, inflating every score."""
    d = df[df["gender"] == gender]
    parts = [g.sample(min(len(g), PER_PLAYER_CAP), random_state=seed)
             for _, g in d.groupby("player", sort=False)]
    return pd.concat(parts).sort_values(["player", "year"]).reset_index(drop=True)


def score_gender(d: pd.DataFrame, seed: int = 0) -> dict:
    """Every score for one tour, all on players held out of the metric fit."""
    players = d["player"].to_numpy()
    fit, ev = split_players(players, seed=seed)
    de = d[ev].reset_index(drop=True)
    pl = de["player"].to_numpy()
    mids = de["match_id"].to_numpy()
    meta = {c: de[c].to_numpy()
            for c in ("charted_by", "opponent", "surface", "hand", "year", "match_id")}
    pairs = pair_index(pl, meta, seed=seed)

    out = {"n_perf": len(d), "n_players": d["player"].nunique(),
           "n_fit": int(fit.sum()), "n_eval": int(ev.sum()),
           "n_eval_players": de["player"].nunique(),
           "blocks": {}, "controls": {}, "features": {}, "eval": de}

    dist_by_block = {}
    for name in BLOCK_ORDER:
        feats = BLOCKS[name]
        X = d[feats].to_numpy(float)
        m = fit_metric(X[fit], players[fit])
        Y = apply_metric(X[ev], m)
        dist = pair_dists(Y, pairs)
        dist_by_block[name] = dist
        a, ns, nd = auc_on(pairs, dist)
        D = distances(Y)
        r1, chance, nq = rank1(D, pl, mids)
        # Null: shuffle the identity labels. Anything above 0.5 here would mean the
        # scoring machinery leaks, not that players have signatures.
        shuffled = pl.copy()
        np.random.default_rng(seed + 99).shuffle(shuffled)
        a_null, _, _ = auc_on(relabel(pairs, shuffled), dist)
        out["blocks"][name] = {
            "n_features": len(feats), "auc": a, "auc_null": a_null,
            "rank1": r1, "chance": chance, "n_queries": nq,
            "n_same": ns, "n_diff": nd,
        }
        if name in ("response", "all"):
            out[f"D_{name}"] = D

    # --- controls: the same pair list, filtered. Response block is the headline. ---
    for block in ("response", "all"):
        dist = dist_by_block[block]
        gap = pairs["year_gap"]
        variants = {
            "all pairs": None,
            "different charter": pairs["diff_charter"],
            "same charter": ~pairs["diff_charter"],
            "different opponent": pairs["diff_opponent"],
            "same handedness": pairs["same_hand"],
            "different surface": pairs["diff_surface"],
            "3+ years apart": gap >= 3,
            "6+ years apart": gap >= 6,
            "strict: charter + opponent + surface all differ": (
                pairs["diff_charter"] & pairs["diff_opponent"] & pairs["diff_surface"]),
        }
        out["controls"][block] = {
            k: dict(zip(("auc", "n_same", "n_diff"), auc_on(pairs, dist, v)))
            for k, v in variants.items()
        }

    # --- confound probe: is the *charter* identifiable from the same vectors? ---
    dist_all = dist_by_block["all"]
    ch_pairs = relabel(pairs, meta["charted_by"])
    diff_player = pl[pairs["i"]] != pl[pairs["j"]]
    out["charter_auc"] = auc_on(ch_pairs, dist_all)[0]
    out["charter_auc_diff_player"] = auc_on(ch_pairs, dist_all, diff_player)[0]

    # --- per-feature identity signal (one feature = one distance) ---
    for f in ALL_FEATURES:
        x = de[f].to_numpy(float)
        z = (x - x.mean()) / max(x.std(), 1e-9)
        a, _, _ = auc_on(pairs, np.abs(z[pairs["i"]] - z[pairs["j"]]))
        out["features"][f] = a

    # --- accuracy vs how much of the match we got to watch ---
    D_resp = out["D_response"]
    q = pd.qcut(de["n_points"], 4, labels=False)
    out["by_size"] = []
    for k in range(4):
        idx = np.flatnonzero((q == k).to_numpy())
        sub = D_resp[np.ix_(idx, idx)]
        r1, chance, nq = rank1(sub, pl[idx], mids[idx])
        out["by_size"].append({
            "quartile": k + 1,
            "lo": int(de["n_points"].iloc[idx].min()),
            "hi": int(de["n_points"].iloc[idx].max()),
            "rank1": r1, "chance": chance, "n_queries": nq,
        })

    # --- drift: does a player stop looking like themselves as the years pass? ---
    # Scored per year-gap bin with AUC, not with a distance gap. Two things move between
    # bins and both would corrupt a raw-distance read: performances from distant eras sit
    # further apart whoever hit them (so the different-player median shifts too), and the
    # spread of the distance distribution changes (so a fixed gap in raw units does not
    # mean the same thing in every bin). AUC is rank-based and compares same-player pairs
    # against different-player pairs *from the same bin*, so it is immune to both. The
    # medians are kept alongside for the report table, but the AUC is the claim.
    dist_resp = dist_by_block["response"]
    live = pairs["diff_match"]
    same_m, diff_m = live & pairs["same"], live & ~pairs["same"]
    out["baseline_diff_dist"] = float(np.median(dist_resp[diff_m]))
    bins = [(0, 0), (1, 2), (3, 5), (6, 9), (10, 99)]
    out["drift"] = []
    for lo, hi in bins:
        in_bin = (pairs["year_gap"] >= lo) & (pairs["year_gap"] <= hi)
        m, dm = same_m & in_bin, diff_m & in_bin
        if m.sum() < 50 or dm.sum() < 50:
            continue
        same_med = float(np.median(dist_resp[m]))
        diff_med = float(np.median(dist_resp[dm]))
        bin_auc, _, _ = auc_on(pairs, dist_resp, in_bin)
        out["drift"].append({
            "label": f"{lo}" if lo == hi else (f"{lo}–{hi}" if hi < 99 else f"{lo}+"),
            "auc": bin_auc, "median": same_med, "diff_median": diff_med,
            "n": int(m.sum()),
        })

    # --- per-player: own spread vs the field, and the mutual identity crossings ---
    out["players"] = self_vs_other(D_resp, pl, mids,
                                   min_perf=MIN_PERF_FOR_PLAYER_STATS)
    out["confusable"] = confusable_pairs(D_resp, pl, mids,
                                         min_perf=MIN_PERF_FOR_PLAYER_STATS, top=10)
    out["same_dists"] = dist_resp[same_m]
    out["diff_dists"] = dist_resp[diff_m]
    return out


# ------------------------------ figures ------------------------------

def fig_blocks(res: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(BLOCK_ORDER))
    w = 0.38
    for k, (g, off) in enumerate({"M": -w / 2, "W": w / 2}.items()):
        vals = [res[g]["blocks"][b]["auc"] for b in BLOCK_ORDER]
        bars = ax.bar(x + off, vals, width=w - 0.02, color=COLOR[g],
                      label=GLABEL[g], zorder=3)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.3f}", (b.get_x() + b.get_width() / 2, v),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", fontsize=7, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{b}\n({res['M']['blocks'][b]['n_features']} feat.)"
                        for b in BLOCK_ORDER])
    # Baseline at chance, not at zero: AUC has no meaningful origin, so anchoring the
    # bars at 0.5 makes bar length read as lift above chance instead of as nothing.
    ax.set_ylim(0.5, 0.75)
    _style(ax, "Blind re-identification by feature block (held-out players)",
           "", "verification AUC (0.5 = chance)")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_controls(res: dict, path: Path, block: str = "response") -> None:
    labels = list(res["M"]["controls"][block])
    y = np.arange(len(labels))[::-1]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    h = 0.36
    for g, off in {"M": h / 2, "W": -h / 2}.items():
        vals = [res[g]["controls"][block][k]["auc"] for k in labels]
        bars = ax.barh(y + off, vals, height=h - 0.02, color=COLOR[g],
                       label=GLABEL[g], zorder=3)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.3f}", (v, b.get_y() + b.get_height() / 2),
                        xytext=(4, 0), textcoords="offset points",
                        va="center", fontsize=7, color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0.5, 0.75)
    _style(ax, f"Does the signal survive the confounds? ({block} block)",
           "verification AUC (0.5 = chance)", "")
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower right")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_distances(res: dict, path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, g in zip(axes, ("M", "W")):
        r = res[g]
        lo, hi = 0, np.percentile(r["diff_dists"], 99.5)
        bins = np.linspace(lo, hi, 60)
        ax.hist(r["diff_dists"], bins=bins, density=True, color=MUTED,
                alpha=0.55, label="different players", zorder=3)
        ax.hist(r["same_dists"], bins=bins, density=True, histtype="step",
                color=COLOR[g], linewidth=2, label="same player", zorder=4)
        _style(ax, f"{GLABEL[g].title()} — response block", "distance between performances",
               "density" if g == "M" else "")
        ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    fig.suptitle("Same player vs different players: the overlap is the difficulty",
                 color=INK, fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_size(res: dict, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(7.2, 4))
    r1s = {g: [r["rank1"] for r in res[g]["by_size"]] for g in ("M", "W")}
    for g in ("M", "W"):
        ax.plot([r["quartile"] for r in res[g]["by_size"]], r1s[g], marker="o",
                markersize=7, linewidth=2, color=COLOR[g], label=GLABEL[g], zorder=4)
    _label_ends(ax, r1s, x0=1)          # quartiles are numbered from 1
    ch = np.mean([r["chance"] for g in ("M", "W") for r in res[g]["by_size"]])
    ax.axhline(ch, color=MUTED, linewidth=1, zorder=2)
    ax.annotate(f"chance ≈ {ch:.3f}", (4, ch), xytext=(0, 5),
                textcoords="offset points", ha="right", fontsize=7, color=MUTED)
    rows = res["M"]["by_size"]
    ax.set_xticks([r["quartile"] for r in rows])
    ax.set_xticklabels([f"Q{r['quartile']}\n{r['lo']}–{r['hi']} pts" for r in rows])
    ax.set_ylim(0, None)
    _style(ax, "How much of the match you get to watch (men clearly, women noisily)",
           "performance size (charted points)", "rank-1 accuracy")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_drift(res: dict, path: Path) -> None:
    """AUC per year-gap bin, not a raw distance gap.

    Distances are not comparable between bins: era-separated performances sit further
    apart whoever hit them, and the spread changes too. AUC is rank-based and compares
    like with like inside each bin, so it is the measure that can carry this claim.
    """
    fig, ax = plt.subplots(figsize=(7.6, 4.2))
    aucs = {g: [r["auc"] for r in res[g]["drift"]] for g in ("M", "W")}
    for g in ("M", "W"):
        xs = np.arange(len(aucs[g]))
        ax.plot(xs, aucs[g], marker="o", markersize=7, linewidth=2,
                color=COLOR[g], label=GLABEL[g], zorder=4)
    _label_ends(ax, aucs)
    rows = res["M"]["drift"]
    last = len(rows) - 1
    ax.axvspan(last - 0.35, last + 0.45, color=GRID, alpha=0.45, zorder=1)
    # Park the caveat in the empty lower part of the shaded band, clear of both lines.
    ax.annotate("survivorship:\nonly decade-spanning\ncareers reach\nthis band",
                (last, 0.585), ha="center", va="top", fontsize=7, color=MUTED)
    ax.set_xticks(np.arange(len(rows)))
    ax.set_xticklabels([r["label"] for r in rows])
    ax.set_ylim(0.5, None)
    _style(ax, "Recognisability fades with the years between two performances",
           "years between the two performances",
           "verification AUC within the gap band (0.5 = chance)")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="lower left")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ------------------------------ report ------------------------------

def write_report(res: dict, path: Path) -> None:
    md = ["# Blind re-identification: can you tell who is across the net?", ""]
    md.append("*Generated by `experiments/blind_reid/run.py`. The unit is one "
              "**performance** — a single player in a single match — vectorized from the "
              "decoded notation with the name stripped. Scores are **verification AUC** "
              "(the chance a same-player pair is closer than a different-player pair; "
              "0.5 = chance) and **rank-1 accuracy** (is a performance's nearest "
              "neighbour the same player), each computed only on players held out of the "
              "distance metric's fit.*")
    md.append("")

    for g in ("M", "W"):
        r = res[g]
        md.append(f"- **{GLABEL[g].title()}:** {r['n_perf']:,} performances, "
                  f"{r['n_players']} players (capped at {PER_PLAYER_CAP} per player); "
                  f"metric fit on {r['n_fit']:,}, scored on {r['n_eval']:,} from "
                  f"{r['n_eval_players']} held-out players.")
    md.append("")

    md.append("## Headline: yes, and the serve is not how")
    md.append("")
    md.append("| block | features | AUC (men) | AUC (women) | rank-1 (men) | chance | "
              "rank-1 (women) | chance |")
    md.append("|---|---|---|---|---|---|---|---|")
    for b in BLOCK_ORDER:
        m, w = res["M"]["blocks"][b], res["W"]["blocks"][b]
        md.append(f"| **{b}** | {m['n_features']} | {m['auc']:.3f} | {w['auc']:.3f} | "
                  f"{m['rank1']:.3f} | {m['chance']:.4f} | "
                  f"{w['rank1']:.3f} | {w['chance']:.4f} |")
    md.append("")
    mm, wm = res["M"]["blocks"], res["W"]["blocks"]
    md.append(f"Shuffling the identity labels collapses every block to chance "
              f"(null AUC {mm['all']['auc_null']:.3f} men, {wm['all']['auc_null']:.3f} "
              "women), so the machinery is not leaking.")
    md.append("")
    md.append("![blocks](figures/blind_reid_blocks.png)")
    md.append("")
    md.append("The **response** block — returns plus rally strokes, nothing about the "
              "delivery — beats the **serve** block outright "
              f"({mm['response']['auc']:.3f} vs {mm['serve']['auc']:.3f} for the men, "
              f"{wm['response']['auc']:.3f} vs {wm['serve']['auc']:.3f} for the women), "
              "and the rally strokes alone are enough to do it "
              f"({mm['rally']['auc']:.3f} men from {mm['rally']['n_features']} features). "
              "So the intuition that you would name your opponent from their serve is "
              "backwards: the serve is the *weakest* of the three views. What gives a "
              "player away is what comes back once the point is live.")
    md.append("")
    md.append(f"Rank-1 accuracy on the response block is {mm['response']['rank1']:.3f} "
              f"against a chance rate of {mm['response']['chance']:.4f} — "
              f"{mm['response']['rank1'] / mm['response']['chance']:.0f}x chance, from "
              "one match, with the serve withheld and against a gallery of every other "
              "held-out performance.")
    md.append("")

    md.append("## Which single measurements carry identity")
    md.append("")
    feats = sorted(res["M"]["features"].items(), key=lambda kv: -kv[1])
    md.append("Single-feature AUC (men), top 10 and bottom 5:")
    md.append("")
    md.append("| feature | block | AUC |")
    md.append("|---|---|---|")
    for f, a in feats[:10] + [("…", float("nan"))] + feats[-5:]:
        if f == "…":
            md.append("| … | | |")
            continue
        md.append(f"| `{f}` | {'serve' if f in SERVE_FEATURES else 'response'} | {a:.3f} |")
    md.append("")
    top6 = [f for f, _ in feats[:6]]
    n_resp = sum(f not in SERVE_FEATURES for f in top6)
    count = "All six" if n_resp == 6 else f"{n_resp} of the six"
    md.append(f"{count} of the most identifying single features are response features. "
              "Net-play rate, slice reliance (on the return and in the rally), forehand "
              "share and rally tempo are the fingerprint. Serve *direction* is close to "
              "noise at this resolution, and only ace rate ranks near the top of the "
              "serve block. Court-zone directions (`ral_dir3`, `ret_dir3`, `ret_fh`) are "
              "the weakest features of all: they say more about where the ball ended up "
              "than about who chose to hit it there.")
    md.append("")

    md.append("## The controls")
    md.append("")
    md.append("Each row is the same pair list, filtered — the question is whether the "
              "signal is the player or something correlated with the player.")
    md.append("")
    md.append("| pairs restricted to | AUC (men) | AUC (women) | same-player pairs |")
    md.append("|---|---|---|---|")
    for k in res["M"]["controls"]["response"]:
        m = res["M"]["controls"]["response"][k]
        w = res["W"]["controls"]["response"][k]
        md.append(f"| {k} | {m['auc']:.3f} | {w['auc']:.3f} | {m['n_same']:,} |")
    md.append("")
    md.append("![controls](figures/blind_reid_controls.png)")
    md.append("")
    cr = res["M"]["controls"]["response"]
    strict = "strict: charter + opponent + surface all differ"
    hand_cost = cr["all pairs"]["auc"] - cr["same handedness"]["auc"]
    md.append("The signal is not an artefact. Forcing every pair to differ in charter, "
              "opponent **and** surface at once costs about two points of AUC "
              f"({cr['all pairs']['auc']:.3f} → {cr[strict]['auc']:.3f} for the men). "
              "The charter deserves its own check, since notation habits could easily "
              "masquerade as player habits: asking the same vectors to identify the "
              f"**charter** instead of the player gives AUC "
              f"{res['M']['charter_auc']:.3f} "
              f"({res['M']['charter_auc_diff_player']:.3f} restricted to "
              "different-player pairs), barely above chance. Conditioning every rate on "
              "charted denominators (see `features.py`) is what buys that.")
    md.append("")
    md.append("Handedness contributes a little but is nowhere near the whole story: "
              "restricting to same-handed pairs, where lefty-vs-righty can no longer "
              f"help, costs {hand_cost:.3f} AUC.")
    md.append("")

    md.append("## Are players more like each other than like their past selves?")
    md.append("")
    md.append("This was the question the experiment was built for. The answer is mostly "
              "no: players are their own nearest kind, and clearly so.")
    md.append("")
    for g in ("M", "W"):
        p = pd.DataFrame(res[g]["players"])
        n_cross = int((p["median_self"] > p["median_other"]).sum())
        md.append(f"- **{GLABEL[g].title()}:** of {len(p)} held-out players with "
                  f"{MIN_PERF_FOR_PLAYER_STATS}+ scored performances, **{n_cross}** "
                  f"({n_cross / len(p):.0%}) sit further from their own other showings "
                  "than from the field's. Median own-spread "
                  f"{p['median_self'].median():.2f} vs {p['median_other'].median():.2f} "
                  "to the field.")
    md.append("")
    md.append("![distances](figures/blind_reid_distances.png)")
    md.append("")
    md.append("Time does erode it, though, and by a measurable amount. Scored inside each "
              "gap band, men's AUC falls from "
              f"{res['M']['drift'][0]['auc']:.3f} for pairs from the same season to "
              f"{res['M']['drift'][-2]['auc']:.3f} at six to nine years apart, which is "
              "roughly a third of the lift above chance. So a player is still clearly "
              "recognisable years later, just less reliably. That lines up with "
              "`career_splits` rather than cutting against it: styles really do drift, "
              "and this puts a rate on it.")
    md.append("")
    md.append("![drift](figures/blind_reid_drift.png)")
    md.append("")
    md.append("That figure is scored with AUC rather than with a distance, and the reason "
              "is worth stating because the distance version misleads. A player's raw "
              "distance to their own older performances does grow with the year gap "
              f"(men: {res['M']['drift'][0]['median']:.2f} at no gap to "
              f"{res['M']['drift'][-1]['median']:.2f} at ten years and up), which looks "
              "like decay. But two things move between bins. Performances from distant "
              "eras sit further apart whoever hit them, so the different-player median "
              "shifts as well, and the spread of the distribution changes, so a fixed gap "
              "in raw units does not mean the same thing in every bin. AUC is rank-based "
              "and pits same-player pairs against different-player pairs *from the same "
              "bin*, so it is immune to both:")
    md.append("")
    md.append("| years apart | AUC (men) | AUC (women) | men: same-player median | "
              "men: different-player median | men: same-player pairs |")
    md.append("|---|---|---|---|---|---|")
    for rm, rw in zip(res["M"]["drift"], res["W"]["drift"]):
        md.append(f"| {rm['label']} | {rm['auc']:.3f} | {rw['auc']:.3f} | "
                  f"{rm['median']:.2f} | {rm['diff_median']:.2f} | {rm['n']:,} |")
    md.append("")
    last = res["M"]["drift"][-1]
    md.append(f"Two things in that table need flagging. The **{last['label']} band "
              f"rebounds** (men {last['auc']:.3f}), and that is not a recovery of "
              f"identity: it rests on {last['n']:,} same-player pairs, it can only contain "
              "players charted across a decade or more, and its different-player median "
              f"jumps to {last['diff_median']:.2f}, so era separation is helping tell "
              "strangers apart too.")
    md.append("")
    mc = res["M"]["controls"]["response"]
    md.append("And the **cumulative year-gap rows in the controls table above are "
              f"flattered** by the same effect. \"6+ years apart\" reads "
              f"{mc['6+ years apart']['auc']:.3f} there, well above the "
              f"{res['M']['drift'][-2]['auc']:.3f} of the six-to-nine band, because "
              "pooling six-to-nine with ten-plus mixes two distance scales and lets "
              "same-player pairs from the tighter band beat different-player pairs from "
              "the wider one. The per-band numbers are the ones to trust; the cumulative "
              "rows are kept because they are the natural first thing to compute and it is "
              "worth showing why they mislead.")
    md.append("")
    md.append("Still, the crossings exist. Pairs of **different** players whose "
              "performances sit closer to each other than to either player's own other "
              "showings (men, response block):")
    md.append("")
    md.append("| player A | player B | cross-distance | A's own | B's own |")
    md.append("|---|---|---|---|---|")
    for c in res["M"]["confusable"]:
        md.append(f"| {c['a']} | {c['b']} | {c['cross']:.2f} | "
                  f"{c['self_a']:.2f} | {c['self_b']:.2f} |")
    md.append("")
    names = [n for c in res["M"]["confusable"] for n in (c["a"], c["b"])]
    hog, hits = max(((n, names.count(n)) for n in set(names)), key=lambda t: t[1])
    if hits >= 3:
        md.append(f"Note how often one name recurs: **{hog}** appears in {hits} of the "
                  f"{len(res['M']['confusable'])} listed pairs. The bar is the smaller of "
                  "the two self-distances, so these are genuinely mutual, but a player "
                  "with a wide own cloud will naturally cross with more of the field. "
                  "Read it as style fluidity rather than as a resemblance to any one "
                  "opponent.")
        md.append("")
    p = pd.DataFrame(res["M"]["players"]).assign(
        ratio=lambda t: t["median_self"] / t["median_other"])
    md.append("Tightest own clouds relative to the field (men), the most self-identical "
              "players:")
    md.append("")
    md.append("| player | own spread | to the field | ratio |")
    md.append("|---|---|---|---|")
    for _, row in p.nsmallest(8, "ratio").iterrows():
        md.append(f"| {row['player']} | {row['median_self']:.2f} | "
                  f"{row['median_other']:.2f} | {row['ratio']:.2f} |")
    md.append("")
    md.append("| player | own spread | to the field | ratio |")
    md.append("|---|---|---|---|")
    for _, row in p.nlargest(5, "ratio").iterrows():
        md.append(f"| {row['player']} | {row['median_self']:.2f} | "
                  f"{row['median_other']:.2f} | {row['ratio']:.2f} |")
    md.append("")
    md.append("*(the least self-identical; read these with the era caveat below)*")
    md.append("")

    md.append("## What limits the accuracy")
    md.append("")
    ms, ws = res["M"]["by_size"], res["W"]["by_size"]
    w_series = ", ".join(f"{r['rank1']:.3f}" for r in ws)
    md.append("Not the weakness of the fingerprint, but the size of the sample. Splitting "
              "held-out performances into quartiles by charted points, men's rank-1 rises "
              f"from {ms[0]['rank1']:.3f} in the shortest quarter of matches to "
              f"{ms[-1]['rank1']:.3f} in the longest. The women's series is noisier and "
              f"not monotone ({w_series}), so the size effect is clear for the men and "
              "only directional for the women:")
    md.append("")
    md.append("| quartile | charted points | rank-1 (men) | rank-1 (women) |")
    md.append("|---|---|---|---|")
    for m, w in zip(res["M"]["by_size"], res["W"]["by_size"]):
        md.append(f"| Q{m['quartile']} | {m['lo']}–{m['hi']} | {m['rank1']:.3f} | "
                  f"{w['rank1']:.3f} |")
    md.append("")
    md.append("![size](figures/blind_reid_size.png)")
    md.append("")
    md.append("A rate estimated from a 90-point match is mostly sampling noise; the same "
              "rate over a five-setter is a measurement. The identity is presumably there "
              "in both, and we can just read it better in the long one.")
    md.append("")

    md.append("## Caveats")
    md.append("")
    md.append("- **Style, not identity.** A high AUC does not mean these features name a "
              "human; it means they narrow the field. Two players with genuinely similar "
              "games stay confusable no matter how much data we add.")
    md.append("- **Opponent reactivity.** What a player hits back is partly the "
              "opponent's doing. The different-opponent control shows this is not the "
              "main driver, but `avg_rally_len` in particular is a property of the "
              "*match* (both players share it), kept because rally tempo is also a real "
              "trait and dropped pairs from the same match make it non-circular.")
    md.append("- **Era mixes with identity.** The field spans 1960–2026 and pre-1990 "
              "matches are sparse, differently charted, and stylistically distant. Some "
              "players with wide own-spread (Guillermo Vilas is the extreme: own spread "
              "far above the field median, on six performances across 1977–1986 and two "
              "surfaces) are being measured across an era gap, not caught being "
              "inconsistent.")
    md.append("- **Charting coverage skew.** Inherited from the whole repo: later rounds "
              "and bigger names are charted more, so the player mix is not the tour's.")
    md.append("- **Distances are not comparable across year-gap bands.** Both the level "
              "and the spread of the distance distribution shift with the era gap, which "
              "is why the drift analysis is scored with AUC inside each band and why the "
              "cumulative year-gap controls read high. Any future cut along a dimension "
              "that moves the distance scale needs the same treatment.")
    md.append("- **Serve resolution.** The serve block is limited to direction, "
              "in-rate and outcome. Real serve identification would use speed, spin and "
              "toss, none of which the notation records — so \"the serve is the weakest "
              "block\" is a statement about *charted* serve data, not about serves.")
    path.write_text("\n".join(md) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="rebuild the performance table instead of using the parquet cache")
    args = ap.parse_args()

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    df = load_performances(con, cache=CACHE, refresh=args.refresh)
    con.close()
    print(f"{len(df):,} performances "
          f"({df['gender'].value_counts().to_dict()}), {len(ALL_FEATURES)} features")

    res = {}
    for g in ("M", "W"):
        d = prepare(df, g)
        res[g] = score_gender(d)
        r = res[g]
        print(f"[{g}] {r['n_eval']:,} scored performances from {r['n_eval_players']} "
              f"held-out players")
        for b in BLOCK_ORDER:
            bl = r["blocks"][b]
            print(f"     {b:9s} AUC {bl['auc']:.3f} (null {bl['auc_null']:.3f})  "
                  f"rank-1 {bl['rank1']:.3f} vs chance {bl['chance']:.4f}")

    fig_blocks(res, FIG_DIR / "blind_reid_blocks.png")
    fig_controls(res, FIG_DIR / "blind_reid_controls.png")
    fig_distances(res, FIG_DIR / "blind_reid_distances.png")
    fig_size(res, FIG_DIR / "blind_reid_size.png")
    fig_drift(res, FIG_DIR / "blind_reid_drift.png")

    rep = PROJECT_ROOT / "reports"
    write_report(res, rep / "blind_reid.md")
    pd.DataFrame([{"gender": g, "block": b, **res[g]["blocks"][b]}
                  for g in ("M", "W") for b in BLOCK_ORDER]).to_csv(
        rep / "blind_reid_blocks.csv", index=False)
    pd.DataFrame([{"gender": g, "feature": f,
                   "block": "serve" if f in SERVE_FEATURES else "response", "auc": a}
                  for g in ("M", "W") for f, a in res[g]["features"].items()]).to_csv(
        rep / "blind_reid_features.csv", index=False)
    pd.DataFrame([{"gender": g, **p} for g in ("M", "W")
                  for p in res[g]["players"]]).to_csv(
        rep / "blind_reid_players.csv", index=False)
    print("\nwrote reports/blind_reid.md, 3 CSVs, and 5 figures")


if __name__ == "__main__":
    main()
