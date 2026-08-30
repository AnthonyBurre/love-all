"""End-to-end: fingerprint players, cluster into styles, report.

Run:  python experiments/player_styles/run.py

Produces, per gender (kept separate — style spaces differ):
  reports/figures/styles_pca_{men,women}.png      players in PC1-PC2, by cluster
  reports/figures/styles_heatmap_{men,women}.png  what defines each archetype
  reports/player_styles.md                        the named archetypes + exemplars
  reports/player_style_clusters.csv               player -> cluster + how well it fits,
                                                  and the fingerprint behind it
"""

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from cluster import describe, kmeans, pca, silhouette_samples, standardize  # noqa: E402
from fingerprint import FEATURES, build_fingerprints  # noqa: E402

from match_charting_project.analysis.career_eras import load_era_map  # noqa: E402
from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402

FIG_DIR = PROJECT_ROOT / "reports" / "figures"
GLABEL = {"M": "men", "W": "women"}


def archetype_name(centroid, features) -> str:
    """A neutral, centroid-driven label for a cluster.

    Describes the cluster's defining tendencies rather than asserting a loaded
    archetype, and is tuned so the *typical* member fits — e.g. a cluster with a big
    serve but ordinary winner rate is a "big-serving baseliner", not "aggressive"
    (which would jar for the consistent players that land in it). Individual players
    near a boundary may lean toward a neighbour; style is a continuum.
    """
    z = dict(zip(features, centroid))
    if z["net_pct"] > 1.0:
        return "Slice & net specialist" if z["slice_pct"] > 1.5 else "Net-rusher / serve-volleyer"
    if z["slice_pct"] > 1.0 or z["return_slice"] > 1.0:
        return "Slice & variety"
    if z["avg_rally_len"] > 0.4 and z["ace_rate"] < 0:
        return "Baseline grinder / counterpuncher"
    if z["gs_winner_rate"] > 0.4 and z["avg_rally_len"] < 0:
        return "Big serve / first-strike"          # genuinely winner-heavy
    if z["ace_rate"] > 0.2 or z["serve_t"] > 0.3:
        return "Big-serving baseliner"              # big serve, ordinary winner rate
    # The else-branch, and named as one. "All-courter" is a compliment in tennis and it was
    # being paid to whatever this cascade had not already described: the cluster it lands on
    # for the women has *below*-average net play (net_pct -0.16) with every other feature
    # near zero, and it is their largest asserted group, sweeping in Halep and Kasatkina —
    # counterpunchers by any account. A reader who knows the term reads a claim about court
    # coverage and net play that the centroid does not support.
    return "Baseline all-rounder"


def fig_pca(df, scores, lab, clusters, explained, path, title):
    fig, ax = plt.subplots(figsize=(8, 6))
    cmap = plt.get_cmap("tab10")
    for j in sorted(clusters):
        m = lab == j
        ax.scatter(scores[m, 0], scores[m, 1], s=22, color=cmap(j),
                   alpha=0.7, label=f"{j}: {archetype_name(clusters[j]['centroid'], FEATURES)}")
        for name in clusters[j]["exemplars"][:2]:
            i = df.index.get_loc(name)
            ax.annotate(name, (scores[i, 0], scores[i, 1]), fontsize=7,
                        alpha=0.8, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel(f"PC1 ({explained[0]:.0%} var)")
    ax.set_ylabel(f"PC2 ({explained[1]:.0%} var)")
    ax.set_title(title)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_heatmap(clusters, path, title):
    js = sorted(clusters)
    M = np.array([clusters[j]["centroid"] for j in js])
    lim = np.abs(M).max()
    fig, ax = plt.subplots(figsize=(9, 1.1 + 0.5 * len(js)))
    im = ax.imshow(M, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(len(FEATURES)))
    ax.set_xticklabels(FEATURES, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(js)))
    ax.set_yticklabels([f"{j}: {archetype_name(clusters[j]['centroid'], FEATURES)}"
                        for j in js], fontsize=8)
    for r in range(len(js)):
        for c in range(len(FEATURES)):
            ax.text(c, r, f"{M[r, c]:+.1f}", ha="center", va="center", fontsize=6)
    ax.set_title(title)
    fig.colorbar(im, ax=ax, shrink=0.7, label="standardized (z)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


_SPLIT_RE = re.compile(r"^(?P<base>.+) \((?P<y0>\d{4})[–-](?P<y1>\d{4})\)$")

# Above what per-entity silhouette an archetype is worth asserting.
#
# The margin predicts instability sharply: when a fifth of a percent of the corpus was
# removed, the 57 entities whose label changed had a median margin of 0.02 against 0.14
# for the 331 that held. So this is the dial between how often a style is named and how
# often the name survives a trivial change in the data, and it was set by measuring both
# rather than picked a priori. Zero — the point where a player is exactly as close to a
# neighbour as to their own cluster — sounds like the principled line but covers only
# 39% of the churn, which leaves the label wrong about 10% of the time and is the state
# this is meant to fix.
#
# At 0.08 the archetype goes unnamed for 31% of entities and 89% of the churn falls
# inside that set, so among labels still asserted roughly 2% moved under the same
# perturbation, against 15% before. Past here it gets expensive: 0.10 buys six more
# points of churn coverage for nine more points of silence, and 0.12 buys one for twelve.
CONFIDENT_MARGIN = 0.08


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    era_map = load_era_map(con)
    md = ["# Player styles: fingerprint → clusters", ""]
    md.append("*Generated by `experiments/player_styles/run.py`. Each player is a vector "
              "of shot tendencies (serve location, slice/net rates, forehand share, rally "
              "length, shotmaking) built from the decoded notation; k-means groups them "
              "into archetypes. Style is a continuum, so silhouette scores are modest — "
              "treat clusters as soft strata, not species.*")
    md.append("")
    if era_map:
        md.append("*Long, evolving careers are split into early/late **era entities** via the "
                  "`player_eras` layer, so each era clusters on its own — see "
                  "“Career-era splits” below.*")
        md.append("")
    mapping_rows = []

    era_arch: dict = defaultdict(list)   # (gender, base) -> [(y0, y1, archetype)]
    for g in ("M", "W"):
        df = build_fingerprints(con, g, min_points=2000, era_map=era_map)
        X = df[FEATURES].to_numpy(float)
        Z, _, _ = standardize(X)
        # Silhouette is flat (~0.12-0.15) across k >= 3, so among those the count is a
        # presentation choice rather than something the data pins down; 4 reads cleanly and
        # is stable.
        #
        # It is *not* flat including k=2. Measured on
        # the shipped fingerprints: men 0.362 at k=2 against 0.134-0.136 for k=3..5, women
        # 0.506 at k=2 against 0.117-0.151 — so the one split the geometry strongly supports
        # is two-way (net-rushers from everyone else on the men's side, slicers from everyone
        # else on the women's), and every finer cut is a presentational choice laid over a
        # continuum. Four is kept because it matches how the sport talks about itself and
        # because the panel withholds any label whose margin is too thin to trust, which is
        # the honest way to carry a k the geometry does not insist on. See CONFIDENT_MARGIN.
        k = 4
        lab, _, _ = kmeans(Z, k, seed=1)
        sil_i = silhouette_samples(Z, lab)
        sil = float(sil_i.mean())
        sc, _, expl = pca(Z, 2)
        clusters = describe(df, Z, lab, FEATURES)

        label = GLABEL[g]
        fig_pca(df, sc, lab, clusters, expl, FIG_DIR / f"styles_pca_{label}.png",
                f"{label.title()} player styles (k={k})")
        fig_heatmap(clusters, FIG_DIR / f"styles_heatmap_{label}.png",
                    f"{label.title()} style archetypes — defining features (z-scores)")

        n_soft = int((sil_i <= CONFIDENT_MARGIN).sum())
        print(f"[{g}] {len(df)} entities | k={k} (silhouette {sil:.3f}) | "
              f"sizes {[clusters[j]['size'] for j in sorted(clusters)]} | "
              f"between styles: {n_soft} ({n_soft / len(df):.0%})")

        md.append(f"## {label.title()} — {len(df)} entities, {k} archetypes "
                  f"(silhouette {sil:.2f})\n")
        md.append(f"![pca](figures/styles_pca_{label}.png)\n")
        for j in sorted(clusters):
            info = clusters[j]
            md.append(f"### {j}. {archetype_name(info['centroid'], FEATURES)} "
                      f"— {info['size']} players")
            md.append(f"- **Defining:** {info['label']}")
            md.append(f"- **Exemplars:** {', '.join(info['exemplars'])}")
            md.append("")
        md.append(f"![heatmap](figures/styles_heatmap_{label}.png)\n")

        for name, j, s in zip(df.index, lab, sil_i):
            arch = archetype_name(clusters[int(j)]["centroid"], FEATURES)
            row = {
                "player": name, "gender": g, "cluster": int(j),
                "archetype": arch,
                # How much this entity's own cluster beats the next-best one for it.
                # Shipped per player because the label is only worth asserting where
                # this is positive — see CONFIDENT_MARGIN.
                "style_margin": round(float(s), 4),
                "style_confident": int(s > CONFIDENT_MARGIN),
                "n_points": int(df.loc[name, "n_points"]),
            }
            # The fingerprint itself travels with the label, so a consumer can benchmark
            # a player against the style *space* rather than against their cluster's
            # mean. class_relative_wpa does exactly that; recomputing the fingerprint
            # there would be a second definition of style that could drift from this one.
            row.update({f: float(df.loc[name, f]) for f in FEATURES})
            mapping_rows.append(row)
            mobj = _SPLIT_RE.match(name)
            if mobj:
                era_arch[(g, mobj["base"])].append((int(mobj["y0"]), int(mobj["y1"]), arch))
    con.close()

    # Career-era split payoff: which split careers' eras landed in different archetypes.
    diverged, same_names = [], []
    for (g, base), eras in sorted(era_arch.items()):
        if len(eras) < 2:
            continue
        eras.sort()
        if len({a for _, _, a in eras}) > 1:
            chain = " → ".join(f"{y0}–{y1}: {a}" for y0, y1, a in eras)
            diverged.append(f"- **{base}** ({g}) — {chain}")
        else:
            same_names.append(f"{base} ({g})")
    if diverged or same_names:
        n_split = len(diverged) + len(same_names)
        md.append("## Career-era splits (via the `player_eras` layer)\n")
        md.append(f"{n_split} evolving careers were split into early/late entities and "
                  "fingerprinted independently. Where the eras land in **different** archetypes, "
                  "the split captured a real style shift:\n")
        md.append(f"**Diverged into different archetypes ({len(diverged)}):**")
        md.extend(diverged or ["- (none)"])
        md.append("")
        md.append(f"**Stayed in one archetype ({len(same_names)}):** "
                  + (", ".join(same_names) or "none") + "\n")

    (PROJECT_ROOT / "reports" / "player_styles.md").write_text("\n".join(md))
    pd.DataFrame(mapping_rows).to_csv(
        PROJECT_ROOT / "reports" / "player_style_clusters.csv", index=False)
    print("\nwrote reports/player_styles.md, player_style_clusters.csv, and 4 figures")


if __name__ == "__main__":
    main()
