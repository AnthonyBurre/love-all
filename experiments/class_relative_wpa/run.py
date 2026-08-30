"""Class-relative shot quality: rank players against their own style archetype.

The settled design (see ../class_aware_eval): keep ONE style-blind eval as the shared
currency, and put class-awareness in the *benchmark*. So: compute each player's
decision quality (avg win-probability conceded per stroke) with the general eval, then
express it as a deviation from their archetype's mean — controlling for the fact that,
e.g., aggressive shotmakers concede more by style, not necessarily by lack of skill.

Output is just ranking lists for others to slice:
  reports/class_relative_wpa.csv   one row per player, all the numbers
  reports/class_relative_wpa.md    top class-relative overperformers + best-in-class

Reuses the graduated eval + per-player quality (``match_charting_project.shots``) and
archetypes from player_styles; keyed by era entity via the ``player_eras`` layer when it
exists, so split careers are rated per era. No new modelling.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parents[1] / "player_styles"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fingerprint import FEATURES  # noqa: E402

from match_charting_project.analysis.career_eras import load_era_map  # noqa: E402
from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import iter_parsed_points  # noqa: E402
from match_charting_project.shots.quality import player_quality  # noqa: E402
from match_charting_project.shots.winprob import WinProbModel  # noqa: E402

FIT_SAMPLE = 300_000
MIN_SHOTS = 1500
CLUSTERS = PROJECT_ROOT / "reports" / "player_style_clusters.csv"


def _ridge(Z, y, lam):
    """Ridge fit with an unpenalised intercept; returns (prediction, R²)."""
    Zi = np.c_[np.ones(len(Z)), Z]
    pen = np.eye(Zi.shape[1])
    pen[0, 0] = 0.0
    beta = np.linalg.solve(Zi.T @ Zi + lam * pen, Zi.T @ y)
    pred = Zi @ beta
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return pred, (1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0)


def style_benchmark(Z, y, target_r2):
    """Expected shot quality for a player's *style*, as a smooth function of their
    fingerprint rather than the mean of the cluster they were sorted into.

    Why not the cluster mean: it is a step function of style, and the step moves. A
    player near a boundary takes their whole benchmark from whichever side the
    clustering put them on that run, so re-running on 0.16% less data moved 57 of 388
    archetype labels and flipped 92 shot-quality verdicts — 51 of them for players
    whose *own* label never moved and whose measured quality changed in the fourth
    decimal. Their benchmark moved underneath them. Fitted over the feature space
    instead, a player between two styles gets a benchmark between them, and nothing
    lurches when the boundary shifts.

    How hard the model is allowed to work is the one real choice here, and it is not
    free: unregularised, this fingerprint explains ~92% of the variance in shot quality
    and the residual left over is mostly noise — the benchmark would be absorbing the
    skill it is supposed to be measuring against. So λ is not a constant and not chosen
    by cross-validation (which optimises prediction, the wrong target — it would pick
    the model that absorbs the most). It is solved for: the smooth benchmark is
    calibrated to absorb exactly as much variance as the four class means did, so this
    controls for style to the same degree as the published metric and changes only the
    discontinuity. On the current data that lands the two within +0.86 (men) and +0.81
    (women) correlation of each other.
    """
    lo, hi = 1e-3, 1e6
    for _ in range(60):                      # bisect: R² falls monotonically in λ
        mid = (lo * hi) ** 0.5               # geometric, since λ spans decades
        _, r2 = _ridge(Z, y, mid)
        if r2 > target_r2:
            lo = mid
        else:
            hi = mid
    lam = (lo * hi) ** 0.5
    pred, r2 = _ridge(Z, y, lam)
    return pred, lam, r2


def _cv_style_r2(Z, y, folds, lam=1e-6):
    """Out-of-fold R² of the style fingerprint on shot quality, plus the held-out
    predictions themselves.

    Cross-validated rather than in-sample on purpose: 12 features over ~190 players
    fits enough noise that the in-sample number overstates how much of shot quality
    style really accounts for, and the whole point of the comparison below is to set
    that share against a reliability, which noise does not survive.
    """
    pred = np.empty(len(y))
    for f in folds:
        tr = np.setdiff1d(np.arange(len(y)), f)
        mu, ym = Z[tr].mean(0), y[tr].mean()
        Zi = np.c_[np.ones(len(tr)), Z[tr] - mu]
        pen = np.eye(Zi.shape[1])
        pen[0, 0] = 0.0
        beta = np.linalg.solve(Zi.T @ Zi + lam * pen, Zi.T @ (y[tr] - ym))
        pred[f] = np.c_[np.ones(len(f)), Z[f] - mu] @ beta + ym
    ss_tot = float(((y - y.mean()) ** 2).sum())
    return pred, 1.0 - float(((y - pred) ** 2).sum()) / ss_tot


def validate(con, model, g, df, era_map, seed=0):
    """Is avg_wpa_lost measuring shot quality, or rally length?

    Three numbers decide it, and they are computed here rather than asserted in prose
    because prose numbers go stale against a rebuild:

    * **Reliability** — split the player's matches in two by hash, score each half,
      correlate across players, Spearman-Brown back up to full length. This is the
      share of the spread that is a stable player trait rather than sampling noise.
    * **The rally-length confound** — WPA telescopes inside a point, so the total swing
      is near-fixed and dividing by strokes makes the metric identically (concession per
      point) / (strokes per point). The correlation with ``avg_rally_len`` is how much
      of the figure that second factor is running.
    * **Reliable non-style share** — reliability minus the out-of-fold R² of the style
      fingerprint. Style is predicted, not fitted, so what it explains is real variance;
      whatever reliability is left over that style cannot reach is the most the metric
      can be measuring as skill.

    The residual is then measured two ways, because they answer different questions.
    Against ``shipped`` — the λ-solved benchmark ``class_rel_z`` is actually computed
    from — is how much signal the published verdict carries. Against a full fit of the
    fingerprint is what survives removing every bit of style the features can reach, and
    it is the lower number: the λ-solved benchmark absorbs only as much variance as the
    four class means did, so a good deal of style is still sitting in the published
    residual, inflating its apparent stability.
    """
    halves = []
    for h in (0, 1):
        q = player_quality(con, model,
                           where=f"m.gender='{g}' AND hash(match_id) % 2 = {h}",
                           min_shots=MIN_SHOTS // 2, era_map=era_map)
        halves.append(q.set_index("player")["avg_wpa_lost"])
    a, b = halves
    keep = df.set_index("player")
    common = sorted(set(a.index) & set(b.index) & set(keep.index))
    ya, yb = a.loc[common].to_numpy(float), b.loc[common].to_numpy(float)
    r_half = float(np.corrcoef(ya, yb)[0, 1])
    rel = 2 * r_half / (1 + r_half)          # Spearman-Brown, halves -> full length

    sub = keep.loc[common]
    y = sub["avg_wpa_lost"].to_numpy(float)
    rally = sub["avg_rally_len"].to_numpy(float)
    r_rally = float(np.corrcoef(y, rally)[0, 1])

    X = sub[FEATURES].to_numpy(float)
    Z = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1.0)
    idx = np.random.default_rng(seed).permutation(len(y))
    folds = np.array_split(idx, 5)
    pred, cv_r2 = _cv_style_r2(Z, y, folds)
    # What each benchmark leaves behind, measured the same way as the raw metric.
    sb = lambda r: 2 * r / (1 + r)                                    # noqa: E731
    r_full = float(np.corrcoef(ya - pred, yb - pred)[0, 1])
    ship = sub["style_expected"].to_numpy(float)
    r_ship = float(np.corrcoef(ya - ship, yb - ship)[0, 1])
    return {
        "n": len(common), "reliability": rel, "r_rally": r_rally, "cv_style_r2": cv_r2,
        "non_style": max(rel - cv_r2, 0.0),
        "z_reliability": sb(r_ship), "z_reliability_full": sb(r_full),
    }


def main() -> None:
    if not CLUSTERS.exists():
        raise SystemExit("Missing reports/player_style_clusters.csv — run player_styles first.")
    clusters = pd.read_csv(CLUSTERS)[
        ["player", "gender", "archetype", "style_margin", "style_confident", *FEATURES]]
    con = connect(read_only=True)
    era_map = load_era_map(con)   # keys WPA by era entity for split careers (matches clusters)

    frames, checks = [], {}
    for g in ("M", "W"):
        model = WinProbModel().fit(iter_parsed_points(con, where=f"gender='{g}'", sample=FIT_SAMPLE))
        q = player_quality(con, model, where=f"m.gender='{g}'", min_shots=MIN_SHOTS, era_map=era_map)
        df = q.merge(clusters[clusters.gender == g], on=["player", "gender"], how="inner")

        grp = df.groupby("archetype")["avg_wpa_lost"]
        df["archetype_mean"] = grp.transform("mean")
        df["archetype_size"] = grp.transform("size")

        # The control level to match: how much of shot quality the four class means
        # accounted for. Measured rather than assumed, so it tracks the clustering.
        y = df["avg_wpa_lost"].to_numpy(float)
        ss_tot = float(((y - y.mean()) ** 2).sum())
        cluster_r2 = 1.0 - float(((y - df["archetype_mean"].to_numpy(float)) ** 2).sum()) / ss_tot

        X = df[FEATURES].to_numpy(float)
        Z = (X - X.mean(0)) / np.where(X.std(0) > 0, X.std(0), 1.0)
        pred, lam, r2 = style_benchmark(Z, y, cluster_r2)
        df["style_expected"] = pred
        resid = y - pred
        df["class_rel_z"] = resid / resid.std(ddof=1)          # <0 = better than their style
        print(f"[{g}] style benchmark: λ={lam:,.0f} R²={r2:.3f} "
              f"(class means {cluster_r2:.3f}) | between styles: "
              f"{int((df.style_confident == 0).sum())}/{len(df)}")

        # After the benchmark, because it reads style_expected to ask how much signal the
        # published verdict actually carries.
        checks[g] = validate(con, model, g, df, era_map)

        df["rank_overall"] = df["avg_wpa_lost"].rank(method="min").astype(int)
        df["rank_in_archetype"] = grp.rank(method="min").astype(int)
        frames.append(df)
    con.close()

    cols = ["player", "gender", "archetype", "style_margin", "style_confident",
            "shots", "avg_wpa_lost", "accuracy",
            "archetype_mean", "style_expected", "class_rel_z", "rank_overall",
            "rank_in_archetype", "archetype_size"]
    out = pd.concat(frames)[cols].round(4).sort_values(["gender", "class_rel_z"])
    out.to_csv(PROJECT_ROOT / "reports" / "class_relative_wpa.csv", index=False)

    # Brief markdown: what the raw metric turns out to measure, then overperformers vs
    # their style and the best in each archetype.
    md = ["# Class-relative shot quality\n",
          "*Decision quality (avg win-prob conceded per stroke, lower = better) measured "
          "with one style-blind eval, then compared against what a player's own style "
          "predicts. `class_rel_z` < 0 means a player concedes less than their style "
          "predicts. Read the validation section first — the raw metric is mostly style, "
          "and only the class-relative residual carries any skill claim at all. CSV has "
          "every player; below are the highlights.*\n"]

    md.append("## Is `avg_wpa_lost` measuring shot quality?\n")
    md.append("Mostly not. WPA telescopes inside a point, so the total swing is near-fixed "
              "and the per-stroke average is identically *(win probability conceded per "
              "point) / (strokes per point)* — the second factor does most of the work.\n")
    md.append("| | players | reliability | r with rally length | style CV R² | "
              "reliable non-style |")
    md.append("|---|---|---|---|---|---|")
    for g in ("M", "W"):
        c = checks[g]
        md.append(f"| {'Men' if g == 'M' else 'Women'} | {c['n']} | "
                  f"{c['reliability']:.2f} | {c['r_rally']:+.2f} | "
                  f"{c['cv_style_r2']:.2f} | **{c['non_style']:.2f}** |")
    md.append("")
    md.append("Reliability is split-half by match hash, Spearman-Brown corrected. Style "
              "R² is out-of-fold over the 12 fingerprint features, so it is variance style "
              "genuinely predicts rather than variance it can be fitted to. The last column "
              "is reliability minus that: the most of the metric's spread that could be "
              "skill rather than style or noise.\n")
    md.append("The residual — the part `class_rel_z` reports — is the only place a skill "
              "claim can live, and it is much weaker than the raw metric:\n")
    md.append("| | `class_rel_z` reliability | against a full style fit |")
    md.append("|---|---|---|")
    for g in ("M", "W"):
        c = checks[g]
        md.append(f"| {'Men' if g == 'M' else 'Women'} | {c['z_reliability']:+.2f} | "
                  f"{c['z_reliability_full']:+.2f} |")
    md.append("")
    md.append("The left column looks strong, and that is the trap: λ is solved to absorb "
              "only as much variance as the four class means did (see `style_benchmark`), "
              "a third to a half of the total, so plenty of style is still sitting inside "
              "the published residual and lending it a stability that is not skill. The "
              "right column removes every bit of style the fingerprint can reach and is "
              "the honest ceiling on the skill claim: a three-band verdict's worth of "
              "signal, not a score's.\n")
    md.append("What the raw metric ranks, most to least (accuracy score, with the average "
              "rally length of the points they played):\n")
    for g in ("M", "W"):
        sub = out[(out.gender == g)].dropna(subset=["accuracy"]).merge(
            clusters[clusters.gender == g][["player", "avg_rally_len"]], on="player",
            how="left").sort_values("accuracy", ascending=False)
        top, bot = sub.head(4), sub.tail(4)
        md.append(f"| {'Men' if g == 'M' else 'Women'}: top | acc | rally | bottom | acc "
                  "| rally |")
        md.append("|---|---|---|---|---|---|")
        for i in range(4):
            t, b = top.iloc[i], bot.iloc[3 - i]
            md.append(f"| {t.player} | {t.accuracy:.1f} | {t.avg_rally_len:.1f} | "
                      f"{b.player} | {b.accuracy:.1f} | {b.avg_rally_len:.1f} |")
        md.append("")
    md.append("That is a grinder-to-servebot ordering, which is why neither this score nor "
              "the class-relative verdict built on it ships to the site. The panel prints "
              "rally length and no quality judgement at all.\n")
    for g in ("M", "W"):
        sub = out[out.gender == g]
        md.append(f"## {'Men' if g == 'M' else 'Women'}\n")
        md.append("**Best relative to their style** (most below their archetype's mean):\n")
        md.append("| player | archetype | avg_wpa_lost | z | overall rank |")
        md.append("|---|---|---|---|---|")
        for r in sub.dropna(subset=["class_rel_z"]).head(12).itertuples():
            md.append(f"| {r.player} | {r.archetype} | {r.avg_wpa_lost:.3f} | "
                      f"{r.class_rel_z:+.2f} | {r.rank_overall} |")
        md.append("\n**Best in each archetype:**\n")
        for arch, a in sub.groupby("archetype"):
            best = a.sort_values("avg_wpa_lost").iloc[0]
            md.append(f"- *{arch}* ({int(best.archetype_size)} players): "
                      f"**{best.player}** ({best.avg_wpa_lost:.3f})")
        md.append("")
    (PROJECT_ROOT / "reports" / "class_relative_wpa.md").write_text("\n".join(md))
    print(f"wrote reports/class_relative_wpa.csv ({len(out)} players) and class_relative_wpa.md")


if __name__ == "__main__":
    main()
