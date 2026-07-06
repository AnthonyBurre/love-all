"""Surface-aware vs surface-blind match win probability — the A/B.

Run:  python experiments/surface_winprob/run.py

Walk-forward over every charted match in date order: predict pre-match WP from
counters built strictly from earlier days, then update. The baseline uses career
serve/return rates; the variant backs each rate off surface -> career -> tour with
pseudo-count k_s (tuned pre-2020, judged 2020+). Writes reports/surface_winprob.md
and reports/figures/surface_winprob.png.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.winprob_match import MatchWP, matchup_strength  # noqa: E402

K = 100                         # career shrinkage (production value)
KS_GRID = [10, 25, 50, 100, 200, 400]
TEST_FROM = "2020-01-01"
MIN_PRIOR = 3                   # both players need >=3 prior charted matches to count
GLABEL = {"M": "Men", "W": "Women"}
SURFACES = ("Hard", "Clay", "Grass")


def match_log(con):
    """Time-ordered per-match aggregates: who served how well, who won, where."""
    return con.execute("""
        WITH pt AS (
          SELECT match_id,
                 sum(CASE WHEN svr=1 THEN 1 ELSE 0 END) s1n,
                 sum(CASE WHEN svr=1 AND pt_winner=1 THEN 1 ELSE 0 END) s1w,
                 sum(CASE WHEN svr=2 THEN 1 ELSE 0 END) s2n,
                 sum(CASE WHEN svr=2 AND pt_winner=2 THEN 1 ELSE 0 END) s2w,
                 last(pt_winner ORDER BY pt) win
          FROM points WHERE svr IN (1,2) AND pt_winner IN (1,2) GROUP BY match_id
        )
        SELECT m.gender, m.date, m.surface_clean surface, m.best_of,
               m.player1 p1, m.player2 p2, pt.s1n, pt.s1w, pt.s2n, pt.s2w, pt.win
        FROM matches m JOIN pt USING (match_id)
        WHERE m.date IS NOT NULL AND m.gender IN ('M','W') AND m.best_of IN (3,5)
          AND m.surface_clean IN ('Hard','Clay','Grass')
          AND pt.s1n >= 20 AND pt.s2n >= 20
        ORDER BY m.date
    """).df()


class Counters:
    """Walk-forward serve/return counts, career and per-surface, per (gender, player)."""

    def __init__(self, mu):
        self.mu = mu
        self.car = defaultdict(lambda: [0, 0, 0, 0])          # sn, sw, rn, rw
        self.sur = defaultdict(lambda: [0, 0, 0, 0])          # keyed (g, p, surface)
        self.nmatches = defaultdict(int)

    def career(self, g, p):
        c = self.car[(g, p)]
        return ((c[1] + K * self.mu[g]) / (c[0] + K),
                (c[3] + K * (1 - self.mu[g])) / (c[2] + K))

    def surface(self, g, p, s, ks):
        cs, cr = self.car[(g, p)], self.sur[(g, p, s)]
        base_s = (cs[1] + K * self.mu[g]) / (cs[0] + K)
        base_r = (cs[3] + K * (1 - self.mu[g])) / (cs[2] + K)
        return ((cr[1] + ks * base_s) / (cr[0] + ks),
                (cr[3] + ks * base_r) / (cr[2] + ks))

    def update(self, g, s, p, sn, sw, rn, rw):
        for c in (self.car[(g, p)], self.sur[(g, p, s)]):
            c[0] += sn
            c[1] += sw
            c[2] += rn
            c[3] += rw
        self.nmatches[(g, p)] += 1


def walk(df, mu, ks_values):
    """One pass; per match, a prediction per arm (baseline + one per k_s)."""
    C = Counters(mu)
    preds = {ks: [] for ks in ["base", *ks_values]}
    meta = []
    day, cur_day = [], None

    def flush():
        for r in day:
            g = r.gender
            ok = min(C.nmatches[(g, r.p1)], C.nmatches[(g, r.p2)]) >= MIN_PRIOR
            deep = min(C.sur[(g, r.p1, r.surface)][0],
                       C.sur[(g, r.p2, r.surface)][0])       # serve pts on this surface
            meta.append((r.date, g, r.surface, 1.0 if r.win == 1 else 0.0, ok, deep))
            arms = {"base": (C.career(g, r.p1), C.career(g, r.p2))}
            for ks in ks_values:
                arms[ks] = (C.surface(g, r.p1, r.surface, ks),
                            C.surface(g, r.p2, r.surface, ks))
            for arm, ((s1, r1), (s2, r2)) in arms.items():
                p1, p2 = matchup_strength(s1, r1, s2, r2, mu[g])
                preds[arm].append(MatchWP(p1, p2, best_of=int(r.best_of)).pre_match())
        for r in day:
            C.update(r.gender, r.surface, r.p1, r.s1n, r.s1w, r.s2n, r.s2n - r.s2w)
            C.update(r.gender, r.surface, r.p2, r.s2n, r.s2w, r.s1n, r.s1n - r.s1w)

    for r in df.itertuples():
        if cur_day is not None and r.date != cur_day:
            flush()
            day = []
        cur_day = r.date
        day.append(r)
    flush()
    return {a: np.array(v) for a, v in preds.items()}, meta


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_bootstrap(dl, n=2000, seed=11):
    """CI on mean(delta log-loss); negative = variant better."""
    rng = np.random.default_rng(seed)
    means = [dl[rng.integers(0, len(dl), len(dl))].mean() for _ in range(n)]
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def surface_split_table(C, gender, top=6):
    """Face validity: biggest walk-forward hard-vs-clay serve tilts (final counters)."""
    rows = []
    for (g, p, s), c in C.sur.items():
        if g != gender or s not in ("Hard", "Clay") or c[0] < 1500:
            continue
        rows.append((p, s, c[1] / c[0]))
    by_p = defaultdict(dict)
    for p, s, rate in rows:
        by_p[p][s] = rate
    tilts = [(p, d["Hard"] - d["Clay"]) for p, d in by_p.items() if len(d) == 2]
    tilts.sort(key=lambda t: t[1])
    return tilts[:top // 2], tilts[-top // 2:][::-1]


def main():
    con = connect(read_only=True)
    df = match_log(con)
    con.close()
    mu = {g: (grp.s1w.sum() + grp.s2w.sum()) / (grp.s1n.sum() + grp.s2n.sum())
          for g, grp in df.groupby("gender")}

    preds, meta = walk(df, mu, KS_GRID)
    dates = np.array([m[0] for m in meta], dtype="datetime64[ns]")
    gender = np.array([m[1] for m in meta])
    surface = np.array([m[2] for m in meta])
    y = np.array([m[3] for m in meta])
    ok = np.array([m[4] for m in meta])
    test = (dates >= np.datetime64(TEST_FROM)) & ok
    train = (dates < np.datetime64(TEST_FROM)) & ok

    # -- tune k_s on the training era (pooled genders) -----------------------
    ll_base_train = logloss(preds["base"][train], y[train]).mean()
    grid = {ks: logloss(preds[ks][train], y[train]).mean() for ks in KS_GRID}
    best_ks = min(grid, key=grid.get)

    # -- judge once on the test era ------------------------------------------
    out = {}
    for g in ("M", "W"):
        m = test & (gender == g)
        lb = logloss(preds["base"][m], y[m])
        lv = logloss(preds[best_ks][m], y[m])
        lo, hi = paired_bootstrap(lv - lb)
        out[g] = dict(n=int(m.sum()), base=float(lb.mean()), var=float(lv.mean()),
                      d=float((lv - lb).mean()), lo=lo, hi=hi,
                      brier_base=float(((preds["base"][m] - y[m]) ** 2).mean()),
                      brier_var=float(((preds[best_ks][m] - y[m]) ** 2).mean()))

    by_surface = {}
    for s in SURFACES:
        m = test & (surface == s)
        lb, lv = logloss(preds["base"][m], y[m]), logloss(preds[best_ks][m], y[m])
        lo, hi = paired_bootstrap(lv - lb)
        by_surface[s] = dict(n=int(m.sum()), d=float((lv - lb).mean()), lo=lo, hi=hi)

    # Robustness: does it still lose where both players have deep surface history
    # (the only regime a selective, ship-it-when-safe version could target)?
    deep = np.array([m[5] for m in meta])
    deep_out = {}
    for thr in (500, 1500):
        m = test & (deep >= thr)
        lb, lv = logloss(preds["base"][m], y[m]), logloss(preds[best_ks][m], y[m])
        lo, hi = paired_bootstrap(lv - lb)
        deep_out[thr] = dict(n=int(m.sum()), d=float((lv - lb).mean()), lo=lo, hi=hi)

    # -- figure: tuning curve + per-surface test deltas -----------------------
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    a1.axhline(ll_base_train, color="gray", ls="--", lw=1, label="baseline (career)")
    a1.plot(KS_GRID, [grid[k] for k in KS_GRID], "o-", color="#1f77b4")
    a1.annotate(f"best k_s={best_ks}", (best_ks, grid[best_ks]),
                textcoords="offset points", xytext=(8, -12), fontsize=9)
    a1.set_xscale("log")
    a1.set_xlabel("surface pseudo-count k_s (log; larger = closer to career)")
    a1.set_ylabel("pre-match log-loss")
    a1.set_title(f"Tuning era (<{TEST_FROM[:4]}, {int(train.sum()):,} matches)")
    a1.legend(fontsize=8)
    xs = np.arange(len(SURFACES))
    ds = [by_surface[s]["d"] for s in SURFACES]
    err = [[by_surface[s]["d"] - by_surface[s]["lo"] for s in SURFACES],
           [by_surface[s]["hi"] - by_surface[s]["d"] for s in SURFACES]]
    a2.axhline(0, color="gray", lw=1)
    a2.bar(xs, ds, yerr=err, capsize=4, color=["#5b8db8", "#b0512e", "#1a7f4b"], alpha=0.85)
    a2.set_xticks(xs, [f"{s}\nn={by_surface[s]['n']:,}" for s in SURFACES])
    a2.set_ylabel("Δ log-loss (surface − baseline)")
    a2.set_title(f"Test era (≥{TEST_FROM[:4]}) — negative = surface-aware better")
    fig.suptitle("Surface-aware match win probability — does the court pay its way?")
    fig.tight_layout()
    fig_path = PROJECT_ROOT / "reports" / "figures" / "surface_winprob.png"
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=110)
    plt.close(fig)

    # -- face validity table --------------------------------------------------
    C = Counters(mu)
    for r in df.itertuples():
        C.update(r.gender, r.surface, r.p1, r.s1n, r.s1w, r.s2n, r.s2n - r.s2w)
        C.update(r.gender, r.surface, r.p2, r.s2n, r.s2w, r.s1n, r.s1n - r.s1w)
    clay_m, hard_m = surface_split_table(C, "M")

    # -- report ----------------------------------------------------------------
    md = ["# Surface-aware match win probability", ""]
    md.append("*Generated by `experiments/surface_winprob/run.py`. One knob: serve/return "
              "rates backed off surface → career → tour with pseudo-count `k_s`, tuned "
              f"pre-{TEST_FROM[:4]}, judged once on {TEST_FROM[:4]}+. Same score tree, same "
              "walk-forward discipline in both arms; matches count only when both players "
              f"have ≥{MIN_PRIOR} prior charted matches.*")
    md.append("")
    md.append(f"Tour anchors: mu = {mu['M']:.3f} (men), {mu['W']:.3f} (women). "
              f"Least-bad `k_s` on the tuning era: **{best_ks}** "
              f"(train log-loss {grid[best_ks]:.4f} vs baseline {ll_base_train:.4f})."
              + (" Note the tuning curve never dips below the baseline line — the tuned "
                 "optimum is effectively `k_s → ∞`, i.e. the baseline itself; the test "
                 "numbers below score the least-bad surface arm for transparency."
                 if grid[best_ks] >= ll_base_train else ""))
    md.append("")
    md.append("## Test-era result")
    md.append("")
    md.append("| | matches | log-loss base | log-loss surface | Δ (95% CI) "
              "| Brier base | Brier surface |")
    md.append("|---|---|---|---|---|---|---|")
    for g in ("M", "W"):
        o = out[g]
        md.append(f"| {GLABEL[g]} | {o['n']:,} | {o['base']:.4f} | {o['var']:.4f} | "
                  f"{o['d']:+.4f} ({o['lo']:+.4f}, {o['hi']:+.4f}) | "
                  f"{o['brier_base']:.4f} | {o['brier_var']:.4f} |")
    md.append("")
    md.append("| surface | matches | Δ log-loss (95% CI) |")
    md.append("|---|---|---|")
    for s in SURFACES:
        b = by_surface[s]
        md.append(f"| {s} | {b['n']:,} | {b['d']:+.4f} ({b['lo']:+.4f}, {b['hi']:+.4f}) |")
    md.append("")
    md.append("Even restricted to matchups where **both** players have deep charted "
              "history on the match's surface — the only regime a selective version "
              "could target — the story holds:")
    md.append("")
    md.append("| both players' surface serve pts | matches | Δ log-loss (95% CI) |")
    md.append("|---|---|---|")
    for thr, b in deep_out.items():
        md.append(f"| ≥{thr:,} | {b['n']:,} | {b['d']:+.4f} ({b['lo']:+.4f}, {b['hi']:+.4f}) |")
    md.append("")
    md.append("![surface winprob](figures/surface_winprob.png)")
    md.append("")
    md.append("## Face validity — the tilt is real even where the payoff is small")
    md.append("")
    md.append("Biggest walk-forward hard-vs-clay serve-rate tilts (men, ≥1,500 serve "
              "points on each):")
    md.append("")
    md.append("| clay-tilted | Δ | hard-tilted | Δ |")
    md.append("|---|---|---|---|")
    for (pc, dc), (ph, dh) in zip(clay_m, hard_m):
        md.append(f"| {pc} | {dc:+.3f} | {ph} | {dh:+.3f} |")
    md.append("")
    verdict_path = PROJECT_ROOT / "reports" / "surface_winprob.md"
    return md, out, by_surface, best_ks, grid, ll_base_train, verdict_path


if __name__ == "__main__":
    md, out, by_surface, best_ks, grid, llb, path = main()
    # verdict appended by hand once numbers are known? No — write it from the numbers.
    better = all(out[g]["d"] < 0 for g in ("M", "W"))
    sig = all(out[g]["hi"] < 0 for g in ("M", "W"))
    md.append("## Verdict")
    md.append("")
    if sig:
        md.append("**Surface awareness pays.** Both genders improve on the held-out era "
                  "with confidence intervals clear of zero — worth graduating into "
                  "`winprob_match` and the site's insights build.")
    elif better:
        md.append("**Directionally positive but not decisive.** Both genders improve on "
                  "the held-out era, but the confidence intervals cross zero — real "
                  "signal exists (see the tuning curve and the tilt table), it's just "
                  "small at the matchup level with charted-sample surface histories. "
                  "Reasonable to ship behind the insights rebuild, clearly labeled; not "
                  "a free win.")
    else:
        md.append("**Does not pay as designed.** The held-out era shows no consistent "
                  "improvement: relative surface tilts are mostly too small or too "
                  "thinly sampled in charted data to move matchup predictions. Keep the "
                  "surface-blind model; revisit only with fuller (non-charted) results "
                  "data per surface.")
    path.write_text("\n".join(md) + "\n")
    print("best ks:", best_ks, "| train LL base/var:",
          f"{llb:.4f}/{grid[best_ks]:.4f}")
    for g in out:
        o = out[g]
        print(f"{g}: n={o['n']}  base {o['base']:.4f}  var {o['var']:.4f}  "
              f"d {o['d']:+.4f} CI ({o['lo']:+.4f},{o['hi']:+.4f})")
    for s, b in by_surface.items():
        print(f"  {s}: n={b['n']}  d {b['d']:+.4f} CI ({b['lo']:+.4f},{b['hi']:+.4f})")
    print("wrote", path)
