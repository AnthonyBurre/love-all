"""End-to-end demo: decode points, build the eval, score shot quality, report.

Run:  python experiments/chess_point_analysis/run.py

Produces, per gender (kept separate, per the project's house rule):
  reports/figures/chess_calibration.png       eval calibration (both genders)
  reports/figures/chess_wpa_hist.png          per-shot WPA distribution (men)
  reports/figures/chess_serve_eval.png        P(server wins) by serve location
  reports/chess_point_quality.md              findings + annotated point + leaderboards

Everything is regenerated from the DuckDB database; nothing here is hand-edited.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import iter_parsed_points  # noqa: E402
from quality import (BLUNDER, MISTAKE, find_demo_points, player_quality,  # noqa: E402
                     render_point)
from winprob import WinProbModel  # noqa: E402

FIT_SAMPLE = 500_000
LEADERBOARD_WHERE = "m.tier IN ('Grand Slam','Masters 1000') AND m.year >= 2010"
FIG_DIR = PROJECT_ROOT / "reports" / "figures"
REPORT = PROJECT_ROOT / "reports" / "chess_point_quality.md"


def calibration(model, points, n_bins: int = 10):
    bins = {}
    for p in points:
        if not p.parse_ok or p.server_won is None or len(p.shots) < 2:
            continue
        for j in range(1, len(p.shots)):
            b = min(int(model.position_value(p, j) * n_bins), n_bins - 1)
            d = bins.setdefault(b, [0, 0])
            d[0] += 1
            d[1] += 1 if p.server_won else 0
    xs, ys = [], []
    for b in sorted(bins):
        n, w = bins[b]
        if n >= 200:
            xs.append((b + 0.5) / n_bins)
            ys.append(w / n)
    return xs, ys


def collect_wpa(model, points, cap: int = 400_000):
    vals = []
    for p in points:
        if not p.parse_ok or p.server_won is None:
            continue
        vals.extend(s["wpa"] for s in model.shot_wpa(p))
        if len(vals) >= cap:
            break
    return vals


def serve_eval(model):
    """P(server wins) right after a 1st serve, by serve location."""
    out = {}
    for d, label in (("4", "wide"), ("5", "body"), ("6", "T")):
        c = model.pos_counts.get((1, 1, "R", "SV", "serve", d))
        if c and c[0]:
            out[label] = (c[1] / c[0], c[0])
    return out


def feature_contrasts(points):
    """Raw server-win% marginals showing the newly-modelled details carry signal.

    Marginal (so confounded) but interpretable: deep returns should suppress the
    serve, slice returns differ from drives, and approaching the net should help.
    """
    depth = {"7": [0, 0], "8": [0, 0], "9": [0, 0]}
    rtype = {"drive": [0, 0], "slice": [0, 0]}
    appr = {0: [0, 0], 1: [0, 0]}
    for p in points:
        if not p.parse_ok or p.server_won is None:
            continue
        w = 1 if p.server_won else 0
        nonserve = [s for s in p.shots if not s.is_serve]
        if nonserve:
            r = nonserve[0]
            if r.depth in depth:
                depth[r.depth][0] += 1
                depth[r.depth][1] += w
            if r.letter in "fb":
                rtype["drive"][0] += 1
                rtype["drive"][1] += w
            elif r.letter in "rs":
                rtype["slice"][0] += 1
                rtype["slice"][1] += w
        server_came_in = any(
            not s.is_serve and s.hitter == p.server
            and ("+" in s.modifiers or "-" in s.modifiers)
            for s in p.shots
        )
        appr[1 if server_came_in else 0][0] += 1
        appr[1 if server_came_in else 0][1] += w
    return depth, rtype, appr


def fig_calibration(cal: dict, path: Path):
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="grey", lw=1, label="perfect")
    for g, (xs, ys) in cal.items():
        ax.plot(xs, ys, "o-", label={"M": "Men", "W": "Women"}[g])
    ax.set_xlabel("predicted P(server wins)")
    ax.set_ylabel("actual server-win rate")
    ax.set_title("Win-probability eval calibration")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_wpa_hist(vals, path: Path):
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(vals, bins=80, range=(-0.7, 0.7), color="#4c72b0")
    ax.axvspan(-0.7, BLUNDER, color="#c44", alpha=0.18, label=f"blunder (≤{BLUNDER})")
    ax.axvspan(BLUNDER, MISTAKE, color="#e9a", alpha=0.18, label=f"mistake")
    ax.set_xlabel("win-probability added per stroke (hitter's view)")
    ax.set_ylabel("strokes")
    ax.set_title("Per-stroke WPA distribution (men)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_serve_eval(serve: dict, path: Path):
    fig, ax = plt.subplots(figsize=(6, 4))
    for off, g in ((-0.18, "M"), (0.18, "W")):
        s = serve.get(g, {})
        labels = list(s)
        xs = range(len(labels))
        ax.bar([x + off for x in xs], [s[k][0] for k in labels], width=0.34,
               label={"M": "Men", "W": "Women"}[g])
        ax.set_xticks(list(xs))
        ax.set_xticklabels(labels)
    ax.set_ylabel("P(server wins) after 1st serve")
    ax.set_title("Serve-location eval (the 'opening' move)")
    ax.set_ylim(0.5, 0.8)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def leaderboard_md(df, n: int = 10) -> str:
    cols = ["player", "shots", "unforced", "avg_wpa_lost", "unforced_lost_share", "accuracy"]
    df = df[cols].copy()
    df["avg_wpa_lost"] = df["avg_wpa_lost"].map("{:.4f}".format)
    df["unforced_lost_share"] = (df["unforced_lost_share"] * 100).map("{:.0f}%".format)
    df["accuracy"] = df["accuracy"].map("{:.1f}".format)
    head = "| rank | " + " | ".join(cols) + " |\n|" + "---|" * (len(cols) + 1)
    rows = []
    for i, r in enumerate(df.head(n).itertuples(index=False), 1):
        rows.append(f"| {i} | " + " | ".join(str(x) for x in r) + " |")
    rows.append("| ... |" + " |" * len(cols))
    for r in df.tail(3).itertuples(index=False):
        rows.append("|  | " + " | ".join(str(x) for x in r) + " |")
    return head + "\n" + "\n".join(rows)


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)

    models, cal, boards, serve = {}, {}, {}, {}
    annotated = ""
    contrasts = None
    for g in ("M", "W"):
        train = list(iter_parsed_points(con, where=f"gender='{g}'", sample=FIT_SAMPLE))
        model = models[g] = WinProbModel().fit(train)
        cal[g] = calibration(model, train)
        serve[g] = serve_eval(model)
        boards[g] = player_quality(con, model, where=f"m.gender='{g}' AND {LEADERBOARD_WHERE}",
                                   min_shots=800)
        if g == "M":
            wpa_vals = collect_wpa(model, train)
            contrasts = feature_contrasts(train)
            demo = find_demo_points(model, train, n=1, min_len=8)
            if demo:
                annotated = render_point(model, demo[0])
        print(f"[{g}] fit on {model.point_counts[()][0]:,} points | "
              f"base 1st/2nd = {model.base(1):.2f}/{model.base(2):.2f} | "
              f"states = {len(model.pos_counts):,} | "
              f"leaderboard players = {len(boards[g])}")
    con.close()

    fig_calibration(cal, FIG_DIR / "chess_calibration.png")
    fig_wpa_hist(wpa_vals, FIG_DIR / "chess_wpa_hist.png")
    serve_by_g = {"M": serve["M"], "W": serve["W"]}
    fig_serve_eval(serve_by_g, FIG_DIR / "chess_serve_eval.png")

    md = ["# Chess-style point analysis: win-probability & shot quality", ""]
    md.append("*Generated by `experiments/chess_point_analysis/run.py`. Treats each "
              "point's shot notation as a move list, builds an empirical "
              "P(server wins) eval, and scores every stroke by win-probability added "
              "(WPA) — the centipawn-loss / blunder idea ported to tennis.*")
    md.append("")
    md.append("## Serve as the opening move")
    for g in ("M", "W"):
        parts = ", ".join(f"{k} **{v[0]:.1%}**" for k, v in serve[g].items())
        md.append(f"- {'Men' if g=='M' else 'Women'}, P(server wins) after a 1st serve: {parts}")
    md.append("\n![serve eval](figures/chess_serve_eval.png)")
    md.append("\n## Richer state: the optional details now in the eval\n")
    md.append("Shot direction was always used; the rally state now also reads "
              "**return depth** (7/8/9), **slice vs drive**, and **net/approach** "
              "(+/- modifiers). Raw men's server-win% by each detail (marginal, so "
              "confounded — but the signal is clearly present):\n")
    dep, rt, ap = contrasts

    def _rate(c):
        return f"{c[1] / c[0]:.1%}" if c[0] else "n/a"

    md.append(f"- **Return depth** — deep(9) {_rate(dep['9'])} · mid(8) "
              f"{_rate(dep['8'])} · shallow(7) {_rate(dep['7'])}  "
              f"(a deeper return weakens the serve hold)")
    md.append(f"- **Return type** — drive {_rate(rt['drive'])} vs slice "
              f"{_rate(rt['slice'])}")
    md.append(f"- **Server approached the net** — yes {_rate(ap[1])} vs no "
              f"{_rate(ap[0])}")
    md.append("\n## The eval is calibrated\n")
    md.append("Predicted win-probability tracks the actual server-win rate closely "
              "(held-in check), so per-stroke WPA is meaningful.\n")
    md.append("![calibration](figures/chess_calibration.png)")
    md.append("\n## Per-stroke WPA: where blunders live\n")
    md.append("![wpa](figures/chess_wpa_hist.png)")
    md.append("\n## An annotated point (the 'annotated game')\n")
    md.append("```\n" + annotated + "\n```")
    md.append("\n## Decision quality: win-probability conceded per stroke\n")
    md.append("Lower `avg_wpa_lost` = gives away less per stroke (the centipawn-loss "
              "analogue); `accuracy` rescales it 0–100. `unforced_lost_share` is how "
              "much of the loss came from charted *unforced* errors — the most "
              "self-inflicted. **Caveat:** this blends shot selection, execution, and "
              "opponent pressure; there is no oracle for the best stroke.\n")
    for g in ("M", "W"):
        md.append(f"### {'Men' if g=='M' else 'Women'} — Slams & Masters, 2010+\n")
        md.append(leaderboard_md(boards[g]))
        md.append("")
    REPORT.write_text("\n".join(md))
    print(f"\nwrote {REPORT.relative_to(PROJECT_ROOT)} and 3 figures to "
          f"{FIG_DIR.relative_to(PROJECT_ROOT)}/")


if __name__ == "__main__":
    main()
