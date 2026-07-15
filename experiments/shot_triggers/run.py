"""Shot-making triggers: attempt rate (winner+unforced) and conversion per lead-up.

Run:  python experiments/shot_triggers/run.py

Recasts shot_patterns' separate winner/error books as one decision (the attempt)
plus execution (conversion). Per player: trigger contexts (attempt-rate lift),
green lights vs traps (conversion vs their own baseline), the winner-vs-error
context correlation (are the two books the same book?), and a pattern-immunity
score (attempt-rate overdispersion vs binomial noise).

The pooled contexts above average over the serve side. A final section splits the
first-four-ply openings — the return, serve+1 and return+1 — by deuce/ad court,
since a wide serve opens opposite wings on the two sides; everything deeper in the
rally stays pooled. Each opening context is scored against the player's own norm
for that same shot and side.

Writes reports/shot_triggers.md, reports/shot_triggers.csv,
reports/shot_triggers_openings.csv, reports/figures/shot_triggers.png.
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shot_language"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from tokens import point_tokens, pretty  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import parse_point  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402

K = 2               # context = the K shots before the player's stroke
MIN_SHOTS = 4000    # a player needs this many contextful strokes to be ranked
MIN_CTX = 60        # a context needs this many of the player's strokes
MIN_ATT = 12        # ...and this many attempts for conversion to mean anything
PHI_MIN_CTX = 20    # contexts needed for the immunity (dispersion) score
TRIGGER_LIFT = 1.5  # attempt lift that counts as a trigger context
TOP = 4
GLABEL = {"M": "Men", "W": "Women"}
MARQUEE = {
    "M": ["Roger Federer", "Novak Djokovic", "Rafael Nadal", "Pete Sampras", "Andre Agassi"],
    "W": ["Serena Williams", "Iga Swiatek", "Martina Navratilova", "Steffi Graf"],
}


# Opening plies to split by serve side: the attempt sits in the first four plies
# (serve, return, and the +1 shots), so context + attempt stay inside the opening.
# (stroke index 0-based, anchor label, serving/returning role). The context is the
# up-to-K prior strokes, so every one of these stays within plies 1-4.
OPEN_ANCHORS = ((1, "return", "return"),      # returner's ball, ctx = (serve,)
                (2, "serve+1", "serve"),      # server's +1,      ctx = (serve, return)
                (3, "return+1", "return"))    # returner's +1,    ctx = (return, serve+1)
OPEN_MIN_BASE = 200   # per (player, side, anchor): strokes needed for a stable baseline


def collect(con, gender: str) -> "tuple[dict, dict]":
    """Pooled per-player context tables (all plies) plus side-split opening tables.

    ``acc``: player -> {n, w, e, ctx:{context: [n, winners, unforced]}} (forced
    excluded) over every ply, sides pooled — unchanged from before.
    ``openings``: (player, side, anchor) -> {base:[n,w,e], ctx:{context:[n,w,e]}}
    for the first-four-ply attempts only, split by deuce/ad.
    """
    acc: dict = defaultdict(lambda: {"n": 0, "w": 0, "e": 0,
                                     "ctx": defaultdict(lambda: [0, 0, 0])})
    openings: dict = defaultdict(lambda: {"base": [0, 0, 0],
                                          "ctx": defaultdict(lambda: [0, 0, 0])})
    sql = (
        "SELECT m.player1, m.player2, p.svr, p.pts, p.first_serve, p.second_serve, "
        "       p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for p1, p2, svr, pts, fs, ss, win in batch:
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            toks = point_tokens(pt)
            names = {1: p1, 2: p2}

            # Side-split openings first — these include short points that end on
            # the return (rally <= K), which the pooled loop below skips.
            side = serve_side(pts)
            if side in ("deuce", "ad"):
                for idx, anchor, _role in OPEN_ANCHORS:
                    if idx >= len(pt.shots):
                        break
                    s = pt.shots[idx]
                    rec = openings[(names[s.hitter], side, anchor)]
                    ctx = tuple(toks[max(0, idx - K):idx])
                    rec["base"][0] += 1
                    c = rec["ctx"][ctx]
                    c[0] += 1
                    if s.terminal == "*":
                        rec["base"][1] += 1
                        c[1] += 1
                    elif s.terminal == "@":
                        rec["base"][2] += 1
                        c[2] += 1

            if len(pt.shots) <= K:
                continue
            for i in range(K, len(pt.shots)):
                a = acc[names[pt.shots[i].hitter]]
                a["n"] += 1
                c = a["ctx"][tuple(toks[i - K:i])]
                c[0] += 1
                term = pt.shots[i].terminal
                if term == "*":
                    a["w"] += 1
                    c[1] += 1
                elif term == "@":
                    a["e"] += 1
                    c[2] += 1
    return acc, openings


def context_table(a: dict) -> "pd.DataFrame":
    """Per qualifying context: attempt rate/lift, conversion, winner/error rates."""
    base_att = (a["w"] + a["e"]) / a["n"]
    base_conv = a["w"] / (a["w"] + a["e"]) if (a["w"] + a["e"]) else 0.0
    rows = []
    for ctx, (n, w, e) in a["ctx"].items():
        if n < MIN_CTX:
            continue
        att = w + e
        rows.append({
            "context": ctx, "n": n, "attempts": att,
            "att_rate": att / n, "att_lift": (att / n) / base_att if base_att else 0.0,
            "conv": w / att if att else np.nan,
            "w_rate": w / n, "e_rate": e / n,
        })
    df = pd.DataFrame(rows)
    df.attrs["base_att"] = base_att
    df.attrs["base_conv"] = base_conv
    return df


def we_correlation(df: "pd.DataFrame") -> float:
    """Across contexts: do winner rate and unforced rate rise together?"""
    if len(df) < PHI_MIN_CTX:
        return np.nan
    return float(np.corrcoef(df.w_rate, df.e_rate)[0, 1])


def dispersion(df: "pd.DataFrame") -> float:
    """sigma: true between-context sd of the attempt rate, in probability points.

    Beta-binomial method of moments — the binomial noise floor is subtracted,
    so heavily-charted players aren't penalized for having tighter estimates:
    E[(k - n*p)^2] = n*p*q + n*(n-1)*sigma^2  summed over contexts.
    0 = the go-for-it decision looks context-blind; large = strongly cue-driven.
    """
    if len(df) < PHI_MIN_CTX:
        return np.nan
    p = df.attempts.sum() / df.n.sum()
    excess = ((df.attempts - df.n * p) ** 2 - df.n * p * (1 - p)).sum()
    denom = (df.n * (df.n - 1)).sum()
    return float(np.sqrt(max(excess / denom, 0.0)))


def tag_contexts(df: "pd.DataFrame") -> "pd.DataFrame":
    """Label each context: trigger + green light / trap, by conversion vs baseline."""
    base_conv = df.attrs["base_conv"]
    out = df.copy()
    out["conv_delta"] = out.conv - base_conv
    out["tag"] = "neutral"
    trig = (out.att_lift >= TRIGGER_LIFT) & (out.attempts >= MIN_ATT)
    out.loc[trig & (out.conv_delta >= 0), "tag"] = "green"
    out.loc[trig & (out.conv_delta < 0), "tag"] = "trap"
    out.attrs = df.attrs
    return out


def _ctx_str(ctx) -> str:
    return " · ".join(pretty(t) for t in ctx)


def player_block(md, player, df):
    base_att, base_conv = df.attrs["base_att"], df.attrs["base_conv"]
    n_all = int(df.n.sum())
    md.append(f"### {player}")
    md.append(f"*goes for it on {base_att:.1%} of strokes, converting {base_conv:.0%}; "
              f"{n_all:,} contextful strokes*\n")
    trig = df[df.tag != "neutral"].sort_values("att_lift", ascending=False)
    md.append("**Trigger sequences** (lead-ups that most raise their attempt rate):")
    for r in trig.head(TOP).itertuples():
        kind = "✅ converts" if r.tag == "green" else "⚠️ trap"
        md.append(f"- `{_ctx_str(r.context)}` → goes for it {r.att_rate:.0%} "
                  f"({r.att_lift:.1f}×), converts {r.conv:.0%} "
                  f"({r.conv_delta:+.0%} vs their norm) {kind} (n={r.n})")
    traps = df[df.tag == "trap"].sort_values("conv_delta")
    if len(traps):
        md.append("\n**Worst traps** (pulled into attempts they don't convert):")
        for r in traps.head(3).itertuples():
            md.append(f"- `{_ctx_str(r.context)}` → attempts {r.att_lift:.1f}× their norm "
                      f"but converts only {r.conv:.0%} vs {base_conv:.0%} baseline (n={r.n})")
    else:
        md.append("\n**No trap contexts** — every sequence that raises their attempt rate "
                  "also meets or beats their usual conversion. Unbaitable (at this "
                  "resolution).")
    md.append("")


def _role_of(anchor: str) -> str:
    return "serve" if anchor == "serve+1" else "return"


def opening_rows(openings: dict, gender: str, qualifying: set) -> list:
    """Tag opening contexts green/trap against the player's own baseline *for the
    same shot and side* (their deuce serve+1 norm, their ad return+1 norm, ...).

    Only non-neutral (trigger) rows survive, matching the pooled analysis: a
    context clears ``MIN_CTX`` strokes, lifts the attempt rate ``TRIGGER_LIFT``x
    over that baseline on ``MIN_ATT``+ attempts, then splits green (conversion
    holds) vs trap (conversion falls). Side is a grouping key, so on the deuce
    side a ``serve wide`` context is a deuce-wide serve — the disambiguation the
    pooled tables can't make."""
    rows = []
    for (player, side, anchor), rec in openings.items():
        if player not in qualifying:
            continue
        bn, bw, be = rec["base"]
        batt = bw + be
        if bn < OPEN_MIN_BASE or batt == 0:
            continue
        base_att, base_conv = batt / bn, bw / batt
        for ctx, (n, w, e) in rec["ctx"].items():
            att = w + e
            if n < MIN_CTX or att < MIN_ATT:
                continue
            att_lift = (att / n) / base_att if base_att else 0.0
            if att_lift < TRIGGER_LIFT:
                continue
            conv = w / att
            conv_delta = conv - base_conv
            rows.append({
                "player": player, "gender": gender, "side": side, "anchor": anchor,
                "role": _role_of(anchor), "context": _ctx_str(ctx), "n": n,
                "attempts": att, "att_rate": round(att / n, 3),
                "att_lift": round(att_lift, 2), "conversion": round(conv, 3),
                "conv_delta": round(conv_delta, 3), "base_att": round(base_att, 3),
                "base_conv": round(base_conv, 3),
                "tag": "green" if conv_delta >= 0 else "trap",
            })
    return rows


def opening_player_block(md: list, player: str, prows: list) -> None:
    """Per-player favorable (green) and trap opening sequences, by role and side."""
    sub = [r for r in prows if r["player"] == player]
    if not sub:
        return
    md.append(f"### {player}\n")
    for role in ("serve", "return"):
        for side in ("deuce", "ad"):
            cell = [r for r in sub if r["role"] == role and r["side"] == side]
            greens = sorted((r for r in cell if r["tag"] == "green"),
                            key=lambda r: -r["att_lift"])[:2]
            traps = sorted((r for r in cell if r["tag"] == "trap"),
                           key=lambda r: r["conv_delta"])[:2]
            if not greens and not traps:
                continue
            md.append(f"**{role.capitalize()}, {side} court**")
            for r in greens:
                md.append(f"- ✅ `{r['context']}` → {r['anchor']} attempt {r['att_rate']:.0%} "
                          f"({r['att_lift']:.1f}×), converts {r['conversion']:.0%} "
                          f"({r['conv_delta']:+.0%} vs norm) (n={r['n']})")
            for r in traps:
                md.append(f"- ⚠️ `{r['context']}` → {r['anchor']} attempt {r['att_rate']:.0%} "
                          f"({r['att_lift']:.1f}×) but converts only {r['conversion']:.0%} "
                          f"({r['conv_delta']:+.0%} vs norm) (n={r['n']})")
            md.append("")


def main() -> None:
    con = connect(read_only=True)
    md = ["# Shot-making triggers — attempts, conversion, traps, immunity", ""]
    md.append("*Generated by `experiments/shot_triggers/run.py`. An **attempt** = the "
              "player's stroke is a winner or an unforced error (they pulled the "
              "trigger); **conversion** = winners / attempts. Per player, contexts (two "
              "prior shots) are tagged **green light** (attempts up, conversion holds) "
              "or **trap** (attempts up, conversion below their norm). σ measures how "
              "context-driven the go-for-it decision is (0 = context-blind), with "
              "binomial sampling noise subtracted.*")
    md.append("")
    csv_rows, player_rows = [], []
    corr_all, phi_rows = [], []
    open_rows, open_by_gender = [], {}
    for g in ("M", "W"):
        acc, openings = collect(con, g)
        tables = {}
        for player, a in acc.items():
            if a["n"] < MIN_SHOTS or (a["w"] + a["e"]) == 0:
                continue
            df = tag_contexts(context_table(a))
            if not len(df):
                continue
            tables[player] = df
            r = we_correlation(df)
            phi = dispersion(df)
            if not np.isnan(r):
                corr_all.append((g, player, r))
            if not np.isnan(phi):
                phi_rows.append((g, player, phi, df.attrs["base_att"], int(df.n.sum())))
            player_rows.append({
                "player": player, "gender": g,
                "att_rate": round(df.attrs["base_att"], 3),
                "conversion": round(df.attrs["base_conv"], 3),
                "sigma": round(phi, 4) if not np.isnan(phi) else None,
                "n_ctx": len(df), "n_traps": int((df.tag == "trap").sum()),
                "n_greens": int((df.tag == "green").sum()),
                "strokes": a["n"],
            })
            for row in df[df.tag != "neutral"].itertuples():
                csv_rows.append({
                    "player": player, "gender": g, "context": _ctx_str(row.context),
                    "n": row.n, "attempts": row.attempts,
                    "att_rate": round(row.att_rate, 3), "att_lift": round(row.att_lift, 2),
                    "conversion": round(row.conv, 3),
                    "conv_delta": round(row.conv_delta, 3), "tag": row.tag,
                })

        rows_g = opening_rows(openings, g, set(tables))
        open_rows += rows_g
        open_by_gender[g] = rows_g

        md.append(f"## {GLABEL[g]}\n")
        for player in MARQUEE[g]:
            if player in tables:
                player_block(md, player, tables[player])

    con.close()

    # -- the "same book?" answer + immunity leaderboards ----------------------
    corr = pd.DataFrame(corr_all, columns=["gender", "player", "r"])
    phi = pd.DataFrame(phi_rows, columns=["gender", "player", "phi", "base_att", "n"])
    phi = phi.sort_values("phi")

    md.append("## Are the winner book and the error book the same book?")
    md.append("")
    md.append(f"Across {len(corr)} qualifying players, the correlation between a "
              "context's winner rate and its unforced-error rate is "
              f"**{corr.r.mean():+.2f} on average** "
              f"({(corr.r > 0).mean():.0%} of players positive). And that *understates* "
              "the overlap: a stroke can't be both a winner and an error, so pure "
              "chance pushes this correlation negative. Sequences that precede winners "
              "also precede errors because both mark the same decision — going for the "
              "finish. `shot_patterns`' green/trouble split partly conflates decision "
              "with execution; attempt + conversion separates them.")
    md.append("")
    md.append("## Pattern-immunity leaderboard (σ)")
    md.append("")
    md.append("σ = the true between-context spread of a player's go-for-it rate, in "
              "probability points, after subtracting binomial sampling noise (so "
              "charting volume doesn't distort the comparison). 0 would mean the "
              "decision to attempt ignores the lead-up entirely.")
    md.append("")
    md.append("| most cue-driven | σ (pp) | most pattern-immune | σ (pp) |")
    md.append("|---|---|---|---|")
    hi, lo = phi.tail(5).iloc[::-1].reset_index(), phi.head(5).reset_index()
    for i in range(5):
        h, m = hi.iloc[i], lo.iloc[i]
        md.append(f"| {h.player} ({h.gender}) | {h.phi * 100:.1f} | {m.player} "
                  f"({m.gender}) | {m.phi * 100:.1f} |")
    md.append("")
    md.append("![shot triggers](figures/shot_triggers.png)")
    md.append("")

    # -- opening sequences split by serve side --------------------------------
    md.append("## Opening sequences by serve side (deuce vs ad)")
    md.append("")
    md.append("The pooled tables above average over the court the point was served to, "
              "but the first four plies mean different things on the two sides: a wide "
              "serve opens the forehand in the deuce court and the backhand in the ad "
              "court. Here the opening attempts — the return, the serve+1, and the "
              "return+1 — are split by side and scored against the player's own norm "
              "*for that same shot and side*. Everything deeper in the rally stays "
              "pooled (above). Full rows in `reports/shot_triggers_openings.csv`; "
              f"{sum(r['tag'] == 'green' for r in open_rows)} green / "
              f"{sum(r['tag'] == 'trap' for r in open_rows)} trap sequences across "
              f"{len({r['player'] for r in open_rows})} players.")
    md.append("")
    for g in ("M", "W"):
        md.append(f"### {GLABEL[g]}\n")
        for player in MARQUEE[g]:
            opening_player_block(md, player, open_by_gender.get(g, []))

    # -- figure ----------------------------------------------------------------
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    a1.hist(corr.r, bins=25, color="#1a7f4b", alpha=0.8)
    a1.axvline(0, color="gray", lw=1)
    a1.axvline(corr.r.mean(), color="black", ls="--", lw=1,
               label=f"mean {corr.r.mean():+.2f}")
    a1.set_xlabel("corr(winner rate, error rate) across contexts, per player")
    a1.set_title("Winners and errors rise in the same contexts")
    a1.legend(fontsize=8)
    a2.hist(phi.phi * 100, bins=25, color="#b0512e", alpha=0.8)
    a2.axvline(0, color="gray", lw=1, label="0 = context-blind")
    a2.set_xlabel("between-context spread of attempt rate σ (prob. points, noise-corrected)")
    a2.set_title("How cue-driven is the go-for-it decision?")
    a2.legend(fontsize=8)
    fig.suptitle("Shot-making triggers: one decision, two outcomes")
    fig.tight_layout()
    figp = PROJECT_ROOT / "reports" / "figures" / "shot_triggers.png"
    figp.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figp, dpi=110)
    plt.close(fig)

    pd.DataFrame(csv_rows).to_csv(PROJECT_ROOT / "reports" / "shot_triggers.csv", index=False)
    pd.DataFrame(player_rows).to_csv(PROJECT_ROOT / "reports" / "shot_triggers_players.csv",
                                     index=False)
    open_cols = ["player", "gender", "side", "role", "anchor", "context", "n", "attempts",
                 "att_rate", "att_lift", "conversion", "conv_delta", "base_att",
                 "base_conv", "tag"]
    pd.DataFrame(open_rows, columns=open_cols).to_csv(
        PROJECT_ROOT / "reports" / "shot_triggers_openings.csv", index=False)
    (PROJECT_ROOT / "reports" / "shot_triggers.md").write_text("\n".join(md) + "\n")
    print(f"players with corr: {len(corr)} | mean r = {corr.r.mean():+.3f} "
          f"| positive: {(corr.r > 0).mean():.0%}")
    print("phi extremes:", phi.head(3)[["player", "phi"]].values.tolist(),
          phi.tail(3)[["player", "phi"]].values.tolist())
    print(f"wrote reports/shot_triggers.md + .csv ({len(csv_rows)} trigger rows) + figure")
    print(f"wrote reports/shot_triggers_openings.csv ({len(open_rows)} side-split rows)")


if __name__ == "__main__":
    main()
