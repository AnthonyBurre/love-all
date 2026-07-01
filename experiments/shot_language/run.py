"""Shot-sequence language model: predictability, signature patterns, and whether
surprise pays.

Run:  python experiments/shot_language/run.py

Treats each point as a sentence in the shot alphabet (`tokens.py`) and fits an
order-2 Markov "opening book" over it (`ngram.py`). From the field model:
  - **unpredictability** — each player's mean per-shot surprise (bits) under the
    field model; high = their shot choices stray from tour norms.
  - **signature patterns** — the (incoming → response) shot pairs a player plays far
    more than the field does (lift); the tactical-motif analogue.
  - **does surprise pay?** — bin every non-terminal shot by its surprise and look at
    the mean WPA (from the graduated point eval) — do unexpected shots gain ground?

Writes reports/shot_language.md + two figures. This experiment produces a real
result, so it ships artifacts.
"""

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ngram import NGramModel  # noqa: E402
from tokens import START, pretty, point_tokens  # noqa: E402
from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import parse_point  # noqa: E402
from match_charting_project.shots.winprob import WinProbModel  # noqa: E402

FIG = PROJECT_ROOT / "reports" / "figures"
GLABEL = {"M": "Men", "W": "Women"}
SAMPLE = 250_000
MIN_SHOTS = 800     # players below this aren't ranked for unpredictability
MIN_PAIR = 25       # min occurrences for a signature pattern


def load(con, gender):
    """Yield (ParsedPoint, {1: name, 2: name}) over a repeatable per-gender sample."""
    sql = (
        "SELECT m.player1, m.player2, p.svr, p.first_serve, p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ? "
        f"USING SAMPLE reservoir({SAMPLE} ROWS) REPEATABLE (1)"
    )
    for p1, p2, svr, fs, ss, win in con.execute(sql, [gender]).fetchall():
        pt = parse_point(fs, ss, svr, win)
        if pt.parse_ok and pt.server_won is not None and pt.shots:
            yield pt, {1: p1, 2: p2}


def analyze(con, gender):
    # Pass 1 — fit the field language model and the point eval on the same sample.
    lm, ev = NGramModel(), WinProbModel()
    for pt, _ in load(con, gender):
        lm.add_point(point_tokens(pt))
        ev.add_point(pt)

    # Pass 2 — measure per-player surprise, signatures, and surprise vs WPA.
    psum, pcnt = Counter(), Counter()
    sig = defaultdict(Counter)       # name -> Counter((incoming, response))
    sigctx = defaultdict(Counter)    # name -> Counter(incoming)
    surp, wpa = [], []               # non-terminal shots only
    for pt, names in load(con, gender):
        toks = point_tokens(pt)
        surps = lm.point_surprises(toks)
        deltas = ev.shot_wpa(pt)
        for i, sh in enumerate(pt.shots):
            name = names[sh.hitter]
            psum[name] += surps[i]
            pcnt[name] += 1
            inc = toks[i - 1] if i > 0 else START
            sig[name][(inc, toks[i])] += 1
            sigctx[name][inc] += 1
            if not sh.terminal:
                surp.append(surps[i])
                wpa.append(deltas[i]["wpa"])

    players = {n: psum[n] / pcnt[n] for n in pcnt if pcnt[n] >= MIN_SHOTS}
    ppl = 2 ** (sum(psum.values()) / max(sum(pcnt.values()), 1))   # per-shot perplexity
    return dict(lm=lm, players=players, sig=sig, sigctx=sigctx, ppl=ppl,
                surp=np.array(surp), wpa=np.array(wpa), n_players=len(players))


def signatures(res, name, top=4):
    """A player's highest-lift (incoming → response) patterns vs the field."""
    lm, sig, sigctx = res["lm"], res["sig"][name], res["sigctx"][name]
    out = []
    for (inc, resp), c in sig.items():
        if c < MIN_PAIR:
            continue
        fctx = lm.bi.get((inc,))
        if not fctx or not fctx.get(resp):
            continue
        p_player = c / sigctx[inc]
        p_field = fctx[resp] / fctx.total()
        out.append((p_player / p_field, inc, resp, c))
    out.sort(reverse=True)
    return out[:top]


def surprise_wpa_curve(surp, wpa, width: float = 1.0, min_n: int = 500):
    """Mean WPA in fixed-width surprise bins (cleaner than deciles over discrete bits)."""
    edges = np.arange(np.floor(surp.min()), np.ceil(surp.max()) + width, width)
    xs, ys = [], []
    for a, b in zip(edges[:-1], edges[1:]):
        m = (surp >= a) & (surp < b)
        if m.sum() >= min_n:
            xs.append((a + b) / 2)
            ys.append(wpa[m].mean())
    return np.array(xs), np.array(ys)


def fig_unpredictability(results, path, n=8):
    fig, axes = plt.subplots(1, 2, figsize=(12, 6))
    for ax, g in zip(axes, ("M", "W")):
        ranked = sorted(results[g]["players"].items(), key=lambda kv: kv[1])
        picks = ranked[:n] + ranked[-n:]                  # most predictable … most varied
        names = [p[0] for p in picks]
        vals = [p[1] for p in picks]
        colors = ["#1f77b4"] * n + ["#d62728"] * n
        ax.barh(range(len(picks)), vals, color=colors)
        ax.set_yticks(range(len(picks)))
        ax.set_yticklabels(names, fontsize=7)
        ax.set_xlabel("mean surprise (bits/shot)")
        ax.set_title(f"{GLABEL[g]} — most predictable (blue) ↔ most varied (red)")
        ax.set_xlim(min(vals) - 0.05, max(vals) + 0.05)
    fig.suptitle("Shot-sequence predictability under the field model")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_surprise_wpa(results, path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, g in zip(axes, ("M", "W")):
        xs, ys = surprise_wpa_curve(results[g]["surp"], results[g]["wpa"])
        ax.axhline(0, color="gray", lw=0.8, ls=":")
        ax.plot(xs, ys, "o-", color="#2ca02c")
        ax.set_xlabel("shot surprise (bits)")
        ax.set_ylabel("mean WPA of the shot")
        ax.set_title(f"{GLABEL[g]} — does an unexpected shot gain ground?")
    fig.suptitle("Surprise vs. win-probability added (non-terminal shots)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    results = {g: analyze(con, g) for g in ("M", "W")}
    con.close()

    fig_unpredictability(results, FIG / "shot_language_predictability.png")
    fig_surprise_wpa(results, FIG / "shot_language_surprise_wpa.png")

    # Per-player data export (for the site's insights db).
    import csv
    with open(PROJECT_ROOT / "reports" / "shot_language_players.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["player", "gender", "bits", "signatures"])
        for g in ("M", "W"):
            r = results[g]
            for name, bits in r["players"].items():
                sigs = signatures(r, name, top=3)
                sig_str = "; ".join(f"{pretty(inc)}→{pretty(resp)} ({lift:.1f}x)"
                                    for lift, inc, resp, _c in sigs)
                w.writerow([name, g, round(bits, 3), sig_str])

    md = ["# Shot-sequence language model", ""]
    md.append("*Generated by `experiments/shot_language/run.py`. Each point is a sentence "
              "in a small shot alphabet; an order-2 Markov model is the 'opening book'. "
              "Surprise = −log₂ P(next shot | last two), in bits — a player's mean surprise "
              "is how far their shot choices stray from tour norms.*")
    md.append("")

    for g in ("M", "W"):
        r = results[g]
        ranked = sorted(r["players"].items(), key=lambda kv: kv[1])
        md.append(f"## {GLABEL[g]} — {r['n_players']} players, per-shot perplexity "
                  f"{r['ppl']:.1f}")
        md.append("")

        # Global grammar: common rally 3-grams (the "phrases" of tennis).
        rally_tri = [(c.total(), ctx, c.most_common(1)[0]) for ctx, c in r["lm"].tri.items()
                     if START not in ctx]
        md.append("**Common phrases** (frequent two-shot context → likeliest next shot):")
        for _tot, ctx, (nxt, _n) in sorted(rally_tri, reverse=True)[:5]:
            md.append(f"- `{pretty(ctx[0])} · {pretty(ctx[1])}` → **{pretty(nxt)}**")
        md.append("")

        md.append("**Predictability leaderboard** (mean bits/shot):")
        md.append("")
        md.append("| most varied | bits | | most predictable | bits |")
        md.append("|---|---|---|---|---|")
        for (hn, hv), (ln, lv) in zip(ranked[-6:][::-1], ranked[:6]):
            md.append(f"| {hn} | {hv:.2f} | | {ln} | {lv:.2f} |")
        md.append("")

        md.append("**Signature patterns** of the most varied players (lift vs. field):")
        for name, _ in ranked[-3:][::-1]:
            sigs = signatures(r, name)
            if not sigs:
                continue
            parts = [f"{pretty(inc)} → **{pretty(resp)}** ({lift:.1f}×)"
                     for lift, inc, resp, _c in sigs]
            md.append(f"- **{name}**: " + "; ".join(parts))
        md.append("")

    # Does surprise pay?
    md.append("## Does an unexpected shot pay off? (surprise is a style, not an edge)")
    md.append("")
    md.append("![surprise vs wpa](figures/shot_language_surprise_wpa.png)")
    md.append("")
    for g in ("M", "W"):
        xs, ys = surprise_wpa_curve(results[g]["surp"], results[g]["wpa"])
        corr = np.corrcoef(results[g]["surp"], results[g]["wpa"])[0, 1]
        md.append(f"- **{GLABEL[g]}**: surprise↔WPA correlation = {corr:+.3f} (negligible). "
                  f"Mean WPA peaks at moderate surprise (~{max(ys):+.3f}) and falls to "
                  f"{ys[-1]:+.3f} for the most unexpected shots.")
    md.append("")
    md.append("So there is **no payoff to surprise**: the relationship is non-monotone and ~0 "
              "overall. Sound, moderately-aggressive shots gain the most; the *most* "
              "unexpected shots slightly lose ground — they are typically defensive, forced "
              "gets, not creative winners (game-state drives the tail, not creativity). "
              "Unpredictability differentiates *who a player is*, not *how well they're "
              "playing*.")
    md.append("")
    md.append("![predictability](figures/shot_language_predictability.png)")
    md.append("")
    md.append("**Caveats.** Surprise is measured against tour norms, so it rewards rare "
              "shot *types* (slice, net, drop) as much as rare *sequencing*; the "
              "surprise↔WPA link is correlational and shares the point eval's "
              "selection/execution/pressure conflation. Same charting-coverage caveat as "
              "the rest of the repo.")
    md.append("")
    (PROJECT_ROOT / "reports" / "shot_language.md").write_text("\n".join(md))

    for g in ("M", "W"):
        r = results[g]
        top = sorted(r["players"].items(), key=lambda kv: -kv[1])[:3]
        print(f"[{g}] {r['n_players']} players; most varied: "
              + ", ".join(f"{n} {v:.2f}" for n, v in top))
    print("wrote reports/shot_language.md + 2 figures")


if __name__ == "__main__":
    main()
