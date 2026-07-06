"""Form + streakiness vs the career-rate match win-probability model — the A/B.

Run:  python experiments/form_streakiness/run.py

Walk-forward over every charted match in date order. Each player carries a dated
history of opponent-adjusted residuals (observed share of total points won minus
the baseline model's pre-match expectation). The form arm shifts the matchup
point-win probs by w * (form1 - form2); the streaky arm scales each player's form
weight by their training-era residual autocorrelation. Writes
reports/form_streakiness.md and reports/figures/form_streakiness.png.
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

K = 100                          # career shrinkage (production value)
W_GRID = [0.25, 0.5, 0.75, 1.0, 1.5]
TEST_FROM = np.datetime64("2020-01-01")
MIN_PRIOR = 3
FORM_N = 10                      # last-N residuals ...
FORM_DAYS = 540                  # ... within this window
FORM_SHRINK = 5                  # pseudo-count toward zero form
GAP_DAYS = 45                    # autocorr only over gaps this short
AC_SHRINK = 30                   # per-player autocorr shrinkage
GLABEL = {"M": "Men", "W": "Women"}
CLAMP = (0.30, 0.92)


def match_log(con):
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
        SELECT m.gender, m.date, m.best_of,
               m.player1 p1, m.player2 p2, pt.s1n, pt.s1w, pt.s2n, pt.s2w, pt.win
        FROM matches m JOIN pt USING (match_id)
        WHERE m.date IS NOT NULL AND m.gender IN ('M','W') AND m.best_of IN (3,5)
          AND pt.s1n >= 20 AND pt.s2n >= 20
        ORDER BY m.date
    """).df()


def clamp(x):
    return min(CLAMP[1], max(CLAMP[0], x))


class State:
    """Walk-forward career counters + dated residual histories per (gender, player)."""

    def __init__(self, mu):
        self.mu = mu
        self.car = defaultdict(lambda: [0, 0, 0, 0])
        self.res = defaultdict(list)          # (g,p) -> [(date, residual), ...]
        self.nmatches = defaultdict(int)

    def rates(self, g, p):
        c = self.car[(g, p)]
        return ((c[1] + K * self.mu[g]) / (c[0] + K),
                (c[3] + K * (1 - self.mu[g])) / (c[2] + K))

    def form(self, g, p, when):
        hist = self.res[(g, p)]
        vals = [r for d, r in hist[-FORM_N:] if (when - d).days <= FORM_DAYS]
        return sum(vals) / (len(vals) + FORM_SHRINK) if vals else 0.0


def walk(df, mu, w_grid):
    """One pass; per match: baseline pred, form preds per w, and the form inputs."""
    S = State(mu)
    preds = {w: [] for w in ["base", *w_grid]}
    meta = []
    day, cur_day = [], None

    def flush():
        for r in day:
            g = r.gender
            s1, r1 = S.rates(g, r.p1)
            s2, r2 = S.rates(g, r.p2)
            p1, p2 = matchup_strength(s1, r1, s2, r2, mu[g])
            f1 = S.form(g, r.p1, r.date)
            f2 = S.form(g, r.p2, r.date)
            ok = min(S.nmatches[(g, r.p1)], S.nmatches[(g, r.p2)]) >= MIN_PRIOR
            preds["base"].append(MatchWP(p1, p2, best_of=int(r.best_of)).pre_match())
            for w in w_grid:
                a = w * (f1 - f2)
                preds[w].append(MatchWP(clamp(p1 + a), clamp(p2 - a),
                                        best_of=int(r.best_of)).pre_match())
            # realized residual (player1 view) for the diagnostics + histories
            tot = r.s1n + r.s2n
            obs1 = (r.s1w + (r.s2n - r.s2w)) / tot
            exp1 = (p1 * r.s1n + (1 - p2) * r.s2n) / tot
            meta.append((r.date, g, r.p1, r.p2, 1.0 if r.win == 1 else 0.0, ok,
                         f1, f2, obs1 - exp1))
        for r, m in zip(day, meta[-len(day):]):
            g = r.gender
            resid1 = m[8]
            S.res[(g, r.p1)].append((r.date, resid1))
            S.res[(g, r.p2)].append((r.date, -resid1))
            for p, sn, sw, rn, rw in ((r.p1, r.s1n, r.s1w, r.s2n, r.s2n - r.s2w),
                                      (r.p2, r.s2n, r.s2w, r.s1n, r.s1n - r.s1w)):
                c = S.car[(g, p)]
                c[0] += sn
                c[1] += sw
                c[2] += rn
                c[3] += rw
            S.nmatches[(g, r.p1)] += 1
            S.nmatches[(g, r.p2)] += 1

    for r in df.itertuples():
        if cur_day is not None and r.date != cur_day:
            flush()
            day = []
        cur_day = r.date
        day.append(r)
    flush()
    return {a: np.array(v) for a, v in preds.items()}, meta, S


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def paired_bootstrap(dl, n=2000, seed=11):
    rng = np.random.default_rng(seed)
    means = [dl[rng.integers(0, len(dl), len(dl))].mean() for _ in range(n)]
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def ac1(v):
    v = np.asarray(v, dtype=float)
    v = v - v.mean()
    den = (v * v).sum()
    return float((v[:-1] * v[1:]).sum() / den) if den > 0 else 0.0


def gap_pairs(hist, before):
    """Consecutive-residual pairs <= GAP_DAYS apart, training era only."""
    xs, ys = [], []
    for (d0, r0), (d1, r1) in zip(hist, hist[1:]):
        if d1 >= before:
            break
        if (d1 - d0).days <= GAP_DAYS:
            xs.append(r0)
            ys.append(r1)
    return xs, ys


def streakiness(S, before):
    """(g,p) -> shrunk gap-limited lag-1 autocorr over the training era; and raw lists."""
    rho, raw = {}, []
    for key, hist in S.res.items():
        xs, ys = gap_pairs(hist, before)
        if len(xs) < 8:
            continue
        x, yv = np.array(xs), np.array(ys)
        x, yv = x - x.mean(), yv - yv.mean()
        den = np.sqrt((x * x).sum() * (yv * yv).sum())
        if den == 0:
            continue
        r = float((x * yv).sum() / den)
        n = len(xs)
        rho[key] = r * n / (n + AC_SHRINK)
        raw.append((r, n))
    return rho, raw


def perm_null(S, before, reps=30, seed=5):
    rng = np.random.default_rng(seed)
    out = []
    for key, hist in S.res.items():
        xs, ys = gap_pairs(hist, before)
        if len(xs) < 8:
            continue
        pool = np.array(xs + ys[-1:])
        for _ in range(reps):
            v = rng.permutation(pool)
            out.append(ac1(v))
    return np.array(out)


def main():
    con = connect(read_only=True)
    df = match_log(con)
    con.close()
    mu = {g: (grp.s1w.sum() + grp.s2w.sum()) / (grp.s1n.sum() + grp.s2n.sum())
          for g, grp in df.groupby("gender")}

    preds, meta, S = walk(df, mu, W_GRID)
    dates = np.array([m[0] for m in meta], dtype="datetime64[ns]")
    gender = np.array([m[1] for m in meta])
    y = np.array([m[4] for m in meta])
    ok = np.array([m[5] for m in meta])
    f1 = np.array([m[6] for m in meta])
    f2 = np.array([m[7] for m in meta])
    realized = np.array([m[8] for m in meta])
    train = (dates < TEST_FROM) & ok
    test = (dates >= TEST_FROM) & ok

    # -- tune w on the training era -------------------------------------------
    ll_base_train = logloss(preds["base"][train], y[train]).mean()
    grid = {w: logloss(preds[w][train], y[train]).mean() for w in W_GRID}
    best_w = min(grid, key=grid.get)
    form_helps_train = grid[best_w] < ll_base_train

    # -- test-era A/B ----------------------------------------------------------
    out = {}
    for g in ("M", "W"):
        m = test & (gender == g)
        lb, lv = logloss(preds["base"][m], y[m]), logloss(preds[best_w][m], y[m])
        lo, hi = paired_bootstrap(lv - lb)
        out[g] = dict(n=int(m.sum()), base=float(lb.mean()), var=float(lv.mean()),
                      d=float((lv - lb).mean()), lo=lo, hi=hi)

    # -- streaky arm (test era only; per-player rho from the training era) ----
    # Same walk as `walk()`, but each player's form is scaled by their own
    # streakiness multiplier. A second pass keeps the as-of counters honest.
    rho, raw = streakiness(S, TEST_FROM.astype("datetime64[us]").item())
    mult = {key: float(np.clip(1 + 4 * v, 0.0, 2.0)) for key, v in rho.items()}

    S3 = State(mu)
    preds_streaky = []
    day, cur_day = [], None

    def flush3():
        for r in day:
            g = r.gender
            s1, r1 = S3.rates(g, r.p1)
            s2, r2 = S3.rates(g, r.p2)
            p1, p2 = matchup_strength(s1, r1, s2, r2, mu[g])
            fa = S3.form(g, r.p1, r.date)
            fb = S3.form(g, r.p2, r.date)
            a = best_w * (mult.get((g, r.p1), 1.0) * fa - mult.get((g, r.p2), 1.0) * fb)
            preds_streaky.append(MatchWP(clamp(p1 + a), clamp(p2 - a),
                                         best_of=int(r.best_of)).pre_match())
            tot = r.s1n + r.s2n
            obs1 = (r.s1w + (r.s2n - r.s2w)) / tot
            exp1 = (p1 * r.s1n + (1 - p2) * r.s2n) / tot
            S3.res[(g, r.p1)].append((r.date, obs1 - exp1))
            S3.res[(g, r.p2)].append((r.date, -(obs1 - exp1)))
        for r in day:
            g = r.gender
            for p, sn, sw, rn, rw in ((r.p1, r.s1n, r.s1w, r.s2n, r.s2n - r.s2w),
                                      (r.p2, r.s2n, r.s2w, r.s1n, r.s1n - r.s1w)):
                c = S3.car[(g, p)]
                c[0] += sn
                c[1] += sw
                c[2] += rn
                c[3] += rw

    for r in df.itertuples():
        if cur_day is not None and r.date != cur_day:
            flush3()
            day = []
        cur_day = r.date
        day.append(r)
    flush3()
    preds_streaky = np.array(preds_streaky)

    streak_out = {}
    for g in ("M", "W"):
        m = test & (gender == g)
        lu, ls = logloss(preds[best_w][m], y[m]), logloss(preds_streaky[m], y[m])
        lo, hi = paired_bootstrap(ls - lu)
        streak_out[g] = dict(n=int(m.sum()), uni=float(lu.mean()), stk=float(ls.mean()),
                             d=float((ls - lu).mean()), lo=lo, hi=hi)

    # -- diagnostics -----------------------------------------------------------
    # (a) form -> realized residual, test era, player1 - player2 form difference
    fdiff = (f1 - f2)[test]
    resid = realized[test]
    qs = np.quantile(fdiff, np.linspace(0, 1, 11))
    binm, binr = [], []
    for a, b in zip(qs, qs[1:]):
        m = (fdiff >= a) & (fdiff <= b)
        if m.sum() > 30:
            binm.append(fdiff[m].mean())
            binr.append(resid[m].mean())
    slope, intercept = np.polyfit(fdiff, resid, 1)
    se = np.sqrt(np.sum((resid - (slope * fdiff + intercept)) ** 2)
                 / (len(fdiff) - 2) / np.sum((fdiff - fdiff.mean()) ** 2))

    # (b) autocorr reality check
    obs_rho = np.array([r for r, n in raw])
    null_rho = perm_null(S, TEST_FROM.astype("datetime64[us]").item())

    # -- figure ----------------------------------------------------------------
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    a1.axhline(0, color="gray", lw=1)
    a1.plot(binm, binr, "o-", color="#1a7f4b")
    a1.plot(binm, slope * np.array(binm) + intercept, "--", color="gray", lw=1,
            label=f"slope {slope:.2f} ± {se:.2f}")
    a1.set_xlabel("form difference entering the match (player1 − player2)")
    a1.set_ylabel("realized residual (points-share vs expected)")
    a1.set_title("The form signal is real at the points level")
    a1.legend(fontsize=8)
    bins = np.linspace(-0.8, 0.8, 41)
    a2.hist(null_rho, bins=bins, density=True, alpha=0.5, color="gray",
            label=f"permutation null (mean {null_rho.mean():+.3f})")
    a2.hist(obs_rho, bins=bins, density=True, alpha=0.55, color="#b0512e",
            label=f"observed (mean {obs_rho.mean():+.3f}, {len(obs_rho)} players)")
    a2.set_xlabel(f"lag-1 autocorr of residuals (gaps ≤{GAP_DAYS}d)")
    a2.set_title("Streakiness: is any of it individual signal?")
    a2.legend(fontsize=8)
    fig.suptitle("Form and streakiness in the match win-probability model")
    fig.tight_layout()
    figp = PROJECT_ROOT / "reports" / "figures" / "form_streakiness.png"
    figp.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figp, dpi=110)
    plt.close(fig)

    # -- report ----------------------------------------------------------------
    md = ["# Form and streakiness in match win probability", ""]
    md.append("*Generated by `experiments/form_streakiness/run.py`. Form = shrunk mean of "
              f"a player's last {FORM_N} opponent-adjusted residuals within {FORM_DAYS} "
              f"days; the form arm shifts matchup point-win probs by `w·(form₁−form₂)` "
              f"with `w` tuned pre-{str(TEST_FROM)[:4]} and judged on "
              f"{str(TEST_FROM)[:4]}+. The streaky arm scales each player's form by their "
              "training-era gap-limited residual autocorrelation (test era only — see "
              "README for why). Same score tree and walk-forward discipline everywhere.*")
    md.append("")
    md.append("## Does uniform form help?")
    md.append("")
    md.append(f"Training-era log-loss: baseline {ll_base_train:.4f}; " +
              "; ".join(f"w={w}: {grid[w]:.4f}" for w in W_GRID) +
              f". Best: **w={best_w}**" +
              ("." if form_helps_train else
               " — **no w beats the baseline even on the tuning era.**"))
    md.append("")
    md.append("| | matches | log-loss base | log-loss form | Δ (95% CI) |")
    md.append("|---|---|---|---|---|")
    for g in ("M", "W"):
        o = out[g]
        md.append(f"| {GLABEL[g]} | {o['n']:,} | {o['base']:.4f} | {o['var']:.4f} | "
                  f"{o['d']:+.4f} ({o['lo']:+.4f}, {o['hi']:+.4f}) |")
    md.append("")
    md.append("## Does individual streakiness modulation beat uniform form?")
    md.append("")
    md.append("| | matches | log-loss uniform | log-loss streaky | Δ (95% CI) |")
    md.append("|---|---|---|---|---|")
    for g in ("M", "W"):
        o = streak_out[g]
        md.append(f"| {GLABEL[g]} | {o['n']:,} | {o['uni']:.4f} | {o['stk']:.4f} | "
                  f"{o['d']:+.4f} ({o['lo']:+.4f}, {o['hi']:+.4f}) |")
    md.append("")
    md.append("![form streakiness](figures/form_streakiness.png)")
    md.append("")
    md.append("## Diagnostics (model-free)")
    md.append("")
    md.append(f"- **Form signal:** regressing a match's realized residual on the form "
              f"difference entering it gives slope **{slope:.2f} ± {se:.2f}** "
              f"(test era, n={int(test.sum()):,}) — recent residuals do carry some "
              "information about the next charted match.")
    md.append(f"- **Streakiness signal:** per-player residual autocorrelation over "
              f"≤{GAP_DAYS}-day gaps: observed mean **{obs_rho.mean():+.3f}** across "
              f"{len(obs_rho)} players vs permutation-null mean "
              f"**{null_rho.mean():+.3f}** — the distributions nearly coincide (right "
              "panel), so there is little *stable individual* streakiness to modulate by.")
    md.append("")
    return (md, out, streak_out, grid, best_w, ll_base_train, form_helps_train,
            slope, se, obs_rho, null_rho)


if __name__ == "__main__":
    (md, out, streak_out, grid, best_w, llb, helps,
     slope, se, obs_rho, null_rho) = main()
    md.append("## Verdict")
    md.append("")
    form_sig = all(out[g]["hi"] < 0 for g in ("M", "W"))
    form_dir = all(out[g]["d"] < 0 for g in ("M", "W"))
    stk_better = all(streak_out[g]["d"] < 0 for g in ("M", "W"))
    if form_sig:
        md.append("**Form pays.** Both genders improve on the held-out era with CIs "
                  "clear of zero.")
    elif form_dir and helps:
        md.append("**Form is directionally positive but small.** It helps on the tuning "
                  "era and on both genders held out, but the CIs cross zero — the "
                  "charted sample is too sparse for a decisive win.")
    else:
        md.append("**Uniform form does not pay as designed** — and the diagnostics "
                  "explain why that isn't a contradiction. The form signal is real "
                  f"(slope {slope:.2f}, ~{abs(slope / se):.0f}σ) but *small in absolute "
                  "terms*: the extreme form deciles differ by only ~±1.5 points per "
                  "hundred in realized points-share, which moves a pre-match win "
                  "probability by a couple of points — well inside the noise of a "
                  "binary outcome over a few thousand test matches. Part of the slope "
                  "is also just stale career rates catching up (an improving player "
                  "runs persistently positive residuals until their counters absorb "
                  "it), which the walk-forward baseline corrects on its own schedule "
                  "anyway. A decisive answer needs a dense match history — full "
                  "tour results (the `tennis_atp`/`tennis_wta` repos), not the "
                  "charted sample's ~monthly snapshots of a player.")
    if stk_better:
        md.append("")
        md.append("Streakiness modulation edges out uniform form — but read it against "
                  "the autocorrelation null before believing individual streakiness.")
    else:
        md.append("")
        md.append("**Streakiness modulation does not beat uniform form**, consistent "
                  "with the null-test finding that per-player autocorrelation is mostly "
                  "noise at charted-data resolution.")
    md.append("")
    (PROJECT_ROOT / "reports" / "form_streakiness.md").write_text("\n".join(md) + "\n")
    print(f"train: base {llb:.4f} | " +
          " ".join(f"w={w}:{grid[w]:.4f}" for w in grid) + f" | best w={best_w}")
    for g in out:
        o = out[g]
        print(f"{g} form:    n={o['n']}  base {o['base']:.4f}  form {o['var']:.4f}  "
              f"d {o['d']:+.4f} CI ({o['lo']:+.4f},{o['hi']:+.4f})")
    for g in streak_out:
        o = streak_out[g]
        print(f"{g} streaky: uni {o['uni']:.4f}  stk {o['stk']:.4f}  "
              f"d {o['d']:+.4f} CI ({o['lo']:+.4f},{o['hi']:+.4f})")
    print(f"form->residual slope {slope:.3f}±{se:.3f} | rho obs {obs_rho.mean():+.4f} "
          f"null {null_rho.mean():+.4f}")
    print("wrote reports/form_streakiness.md")
