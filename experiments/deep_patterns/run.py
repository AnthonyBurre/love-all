"""Deep (3-4 shot) patterns for heavily-charted players — the gold-star screen.

Run:  python experiments/deep_patterns/run.py

For players with >=10k charted points: mine K=3 and K=4 trigger contexts that
(1) beat their own (K-1)-suffix parent at >=1.3x with an exact binomial p<0.005,
(2) replicate above the parent rate in both match-hash halves (>=15 strokes each),
(3) meet the production support floor (>=60 strokes, >=12 aggressive shots). Survivors are
tagged green/trap by conversion like production triggers.

A final section is a side refinement pass over the survivors: each gold
pattern's occurrences whose K-shot window reaches into the first four plies are
split by deuce/ad court, and Fisher exact tests (Holm-corrected across the whole
family) ask whether the aggressive shot frequency or conversion differs between courts.
Discovery itself stays pooled. Writes reports/deep_patterns.{md,csv},
reports/deep_patterns_side.csv + figure.
"""

import sys
import zlib
from collections import defaultdict
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shot_language"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from tokens import point_tokens, pretty  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import aggressive_shot, parse_point  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402

MIN_POINTS = 10_000     # charted points to enter the candidate pool
DEPTHS = (3, 4)         # deep context lengths (production triggers use 2)
MIN_CTX, MIN_ATT = 60, 12          # production support floor
PARENT_LIFT = 1.3       # deep aggressive shot frequency must be >= this x its parent's
P_MAX = 0.005           # exact binomial tail vs the parent rate
HALF_N = 15             # per-half support for the replication gate
GLABEL = {"M": "Men", "W": "Women"}
MARQUEE = {"M": ["Roger Federer", "Novak Djokovic", "Rafael Nadal"],
           "W": ["Serena Williams", "Iga Swiatek"]}


def candidates(con, gender: str) -> set:
    rows = con.execute("""
        WITH pp AS (
          SELECT x.player, count(*) pts FROM points p
          JOIN matches m USING (match_id),
          LATERAL (VALUES (m.player1), (m.player2)) x(player)
          WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?
          GROUP BY x.player)
        SELECT player FROM pp WHERE pts >= ?
    """, [gender, MIN_POINTS]).fetchall()
    return {r[0] for r in rows}


def collect(con, gender: str, pool: set):
    """Per candidate: base [n,att,win]x2 halves + context tables for K=2..4.

    Also builds ``side_tabs``: for each deep context, the [n, att, win] counts of
    its *opening-touching* occurrences — those whose K-shot window reaches into
    the first four plies (serve, return, serve+1, return+1), where the notation
    is side-relative — split by deuce/ad. These feed the heterogeneity pass over
    the pooled gold survivors; mid-rally occurrences are never side-split.
    """
    base = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    tabs = {k: defaultdict(lambda: [0, 0, 0, 0, 0, 0]) for k in (2, *DEPTHS)}
    side_tabs = {k: defaultdict(lambda: [0, 0, 0]) for k in DEPTHS}  # (pl, ctx, side)
    sql = (
        "SELECT p.match_id, m.player1, m.player2, p.svr, p.pts, p.first_serve, "
        "       p.second_serve, p.pt_winner FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for mid, p1, p2, svr, pts, fs, ss, win in batch:
            if p1 not in pool and p2 not in pool:
                continue
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok or len(pt.shots) < 3:
                continue
            toks = point_tokens(pt)
            names = {1: p1, 2: p2}
            h3 = 3 * (zlib.crc32(str(mid).encode()) & 1)
            side = serve_side(pts)
            n_sh = len(pt.shots)
            for i in range(2, n_sh):
                pl = names[pt.shots[i].hitter]
                if pl not in pool:
                    continue
                # winner / own unforced error / forced the reply out: all three are
                # aggressive shots, and everything but the middle one paid off.
                _w, _e, _f = aggressive_shot(pt.shots, i, n_sh)
                att = _w + _e + _f
                w = _w + _f
                b = base[pl]
                b[h3] += 1
                b[h3 + 1] += att
                b[h3 + 2] += w
                for k in tabs:
                    if i >= k:
                        c = tabs[k][(pl, tuple(toks[i - k:i]))]
                        c[h3] += 1
                        c[h3 + 1] += att
                        c[h3 + 2] += w
                if side in ("deuce", "ad"):
                    for k in DEPTHS:
                        # window toks[i-k:i] reaches into plies 1-4 (shots 0..3)
                        if k <= i <= k + 3:
                            s = side_tabs[k][(pl, tuple(toks[i - k:i]), side)]
                            s[0] += 1
                            s[1] += att
                            s[2] += w
    return base, tabs, side_tabs


def binom_tail(k: int, n: int, p: float) -> float:
    """Exact P(X >= k) for X ~ Binomial(n, p)."""
    if p <= 0:
        return 0.0 if k > 0 else 1.0
    if p >= 1:
        return 1.0
    return sum(comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


def mine(base, tabs) -> list:
    """Gold survivors: beat parent, replicate, meet the support floor."""
    out = []
    for k in DEPTHS:
        for (pl, ctx), c in tabs[k].items():
            n, att, win = c[0] + c[3], c[1] + c[4], c[2] + c[5]
            if n < MIN_CTX or att < MIN_ATT:
                continue
            parent = tabs[k - 1].get((pl, ctx[1:]))
            if not parent:
                continue
            pn, patt = parent[0] + parent[3], parent[1] + parent[4]
            if pn == 0 or patt == 0:
                continue
            p_rate = patt / pn
            if att / n < PARENT_LIFT * p_rate:
                continue
            if binom_tail(att, n, p_rate) >= P_MAX:
                continue
            if not (c[0] >= HALF_N and c[3] >= HALF_N
                    and c[1] / c[0] > p_rate and c[4] / c[3] > p_rate):
                continue
            b = base[pl]
            b_att, b_win = b[1] + b[4], b[2] + b[5]
            base_conv = b_win / b_att if b_att else 0.0
            conv = win / att
            out.append({
                "player": pl, "depth": k, "context": ctx, "n": n, "attempts": att,
                "att_rate": att / n, "parent_rate": p_rate,
                "parent_lift": (att / n) / p_rate,
                "conversion": conv, "conv_delta": conv - base_conv,
                "tag": "green" if conv >= base_conv else "trap",
                "strokes": b[0] + b[3],
            })
    return out


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for the 2x2 table [[a, b], [c, d]]."""
    r1, r2, c1 = a + b, c + d, a + c
    n = r1 + r2
    if min(r1, r2, c1, n - c1) <= 0:
        return 1.0
    lo, hi = max(0, c1 - r2), min(r1, c1)
    denom = comb(n, c1)
    probs = [comb(r1, x) * comb(r2, c1 - x) / denom for x in range(lo, hi + 1)]
    p_obs = probs[a - lo]
    return min(1.0, sum(p for p in probs if p <= p_obs * (1 + 1e-9)))


def holm(pvals: list) -> list:
    """Holm step-down adjusted p-values, returned in the input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj, running = [1.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def side_heterogeneity(rows: list, side_tabs_by_gender: dict, alpha: float = 0.05):
    """Annotate gold survivors with a deuce/ad split of their opening occurrences.

    Discovery stays pooled; this is a refinement pass. For each gold pattern the
    opening-touching occurrences are split by side and two Fisher exact tests ask
    whether the aggressive shot frequency (needs >=HALF_N strokes per side) or the conversion
    (needs >=MIN_ATT/2 aggressive shots per side) differs between courts. Holm correction
    runs across every test performed, so a ``side_diff`` flag means the pattern
    genuinely behaves differently by court; everything else keeps its pooled
    estimate with evidence that pooling is justified.
    """
    tests = []  # (row, field) pairs sharing one Holm family
    for r in rows:
        tabs = side_tabs_by_gender[r["gender"]][r["depth"]]
        nd, ad_, wd = tabs.get((r["player"], r["context"], "deuce"), (0, 0, 0))
        na, aa, wa = tabs.get((r["player"], r["context"], "ad"), (0, 0, 0))
        r.update({
            "n_deuce": nd, "att_deuce": ad_, "win_deuce": wd,
            "n_ad": na, "att_ad": aa, "win_ad": wa,
            "att_rate_deuce": ad_ / nd if nd else None,
            "att_rate_ad": aa / na if na else None,
            "conv_deuce": wd / ad_ if ad_ else None,
            "conv_ad": wa / aa if aa else None,
            "p_att": None, "p_conv": None,
            "p_att_holm": None, "p_conv_holm": None, "side_diff": "",
        })
        if nd >= HALF_N and na >= HALF_N:
            r["p_att"] = fisher_two_sided(ad_, nd - ad_, aa, na - aa)
            tests.append((r, "att"))
        if ad_ >= MIN_ATT // 2 and aa >= MIN_ATT // 2:
            r["p_conv"] = fisher_two_sided(wd, ad_ - wd, wa, aa - wa)
            tests.append((r, "conv"))
    adj = holm([r[f"p_{f}"] for r, f in tests])
    for (r, f), p in zip(tests, adj):
        r[f"p_{f}_holm"] = p
        if p < alpha:
            r["side_diff"] = (r["side_diff"] + "+" + f).lstrip("+")
    return len(tests)


def _ctx_str(ctx) -> str:
    return " · ".join(pretty(t) for t in ctx)


def main():
    con = connect(read_only=True)
    all_rows = []
    side_tabs_by_gender = {}
    pool_sizes = {}
    for g in ("M", "W"):
        pool = candidates(con, g)
        pool_sizes[g] = len(pool)
        base, tabs, side_tabs = collect(con, g, pool)
        side_tabs_by_gender[g] = side_tabs
        rows = mine(base, tabs)
        for r in rows:
            r["gender"] = g
        all_rows += rows
    con.close()
    n_tests = side_heterogeneity(all_rows, side_tabs_by_gender)
    df = pd.DataFrame(all_rows)

    # -- figure: how deep-pattern counts scale with coverage -------------------
    fig, ax = plt.subplots(figsize=(7.5, 4.4))
    if len(df):
        per = df.groupby(["gender", "player"]).agg(
            gold=("player", "size"), strokes=("strokes", "first")).reset_index()
        for g, color in (("M", "#1a7f4b"), ("W", "#b0512e")):
            sub = per[per.gender == g]
            ax.scatter(sub.strokes / 1000, sub.gold, color=color, alpha=0.7,
                       label=GLABEL[g])
        top = per.sort_values("gold", ascending=False).head(6)
        for r in top.itertuples():
            ax.annotate(r.player.split()[-1], (r.strokes / 1000, r.gold),
                        textcoords="offset points", xytext=(5, 3), fontsize=8)
    ax.set_xlabel("contextful strokes (thousands)")
    ax.set_ylabel("gold deep patterns (K=3/4 survivors)")
    ax.set_title("Deep patterns exist — but only where coverage is huge")
    ax.legend(fontsize=8)
    fig.tight_layout()
    figp = PROJECT_ROOT / "reports" / "figures" / "deep_patterns.png"
    figp.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figp, dpi=110)
    plt.close(fig)

    # -- report -----------------------------------------------------------------
    md = ["# Deep patterns — 3–4 shot sequences for the heavily charted", ""]
    md.append("*Generated by `experiments/deep_patterns/run.py`. A deep context earns "
              "**gold** only if it beats its own (K−1)-shot parent (≥1.3×, exact "
              f"binomial p<{P_MAX}), replicates above the parent in both match-hash "
              "halves, and meets the production support floor. Candidate pool: "
              f"{pool_sizes['M']} men + {pool_sizes['W']} women with "
              f"≥{MIN_POINTS:,} charted points.*")
    md.append("")
    if len(df):
        n_players = df.groupby("gender").player.nunique()
        md.append("| | gold patterns | K=3 | K=4 | players with ≥1 |")
        md.append("|---|---|---|---|---|")
        for g in ("M", "W"):
            sub = df[df.gender == g]
            md.append(f"| {GLABEL[g]} | {len(sub)} | {(sub.depth == 3).sum()} | "
                      f"{(sub.depth == 4).sum()} | {n_players.get(g, 0)} |")
        md.append("")
        for g in ("M", "W"):
            md.append(f"## {GLABEL[g]}\n")
            for player in MARQUEE[g]:
                sub = df[(df.gender == g) & (df.player == player)]
                if not len(sub):
                    continue
                md.append(f"### {player} — {len(sub)} gold patterns")
                for r in sub.sort_values("parent_lift", ascending=False).head(5).itertuples():
                    kind = "✅" if r.tag == "green" else "⚠️"
                    md.append(f"- `{_ctx_str(r.context)}` → aggressive "
                              f"{r.att_rate:.0%} vs {r.parent_rate:.0%} without the "
                              f"{'first' if r.depth == 3 else 'first two'} shot(s) "
                              f"({r.parent_lift:.1f}× the parent), converts "
                              f"{r.conversion:.0%} {kind} (n={r.n})")
                md.append("")
    else:
        md.append("**No pattern cleared the gold gates.**")
    md.append("![deep patterns](figures/deep_patterns.png)")
    md.append("")

    # -- side heterogeneity pass over the gold survivors -------------------------
    md.append("## Side heterogeneity (deuce vs ad)")
    md.append("")
    md.append("Discovery stays pooled — halving every sample by court before mining "
              "costs more power than it buys. Instead, each gold pattern's "
              "occurrences whose K-shot window reaches into the first four plies "
              "(where the notation is side-relative) are split deuce/ad, and Fisher "
              "exact tests ask whether the aggressive shot frequency or the conversion differs "
              "between courts, Holm-corrected across the whole family. A flagged "
              "pattern behaves differently by court and is shown split; the rest "
              "keep their pooled estimate with evidence that pooling is justified. "
              "Full per-side rows in `reports/deep_patterns_side.csv`.")
    md.append("")
    if len(df):
        het = df[df.side_diff != ""]
        md.append(f"{n_tests} tests across {len(df)} gold patterns "
                  f"({int(df.p_att.notna().sum())} aggressive-shot-frequency, "
                  f"{int(df.p_conv.notna().sum())} conversion; the rest lacked "
                  f"per-side support) → **{len(het)} pattern"
                  f"{'s' if len(het) != 1 else ''} with a real side difference** "
                  "at Holm-adjusted p<0.05.")
        md.append("")
        diff_name = {"att": "aggressive shot frequency", "conv": "conversion",
                     "att+conv": "aggressive shot frequency and conversion"}
        for r in het.itertuples():
            kind = "✅" if r.tag == "green" else "⚠️"
            md.append(f"### {r.player} — `{_ctx_str(r.context)}` {kind}")
            md.append(f"- differs by court in **{diff_name[r.side_diff]}**: "
                      f"deuce fires {r.att_rate_deuce:.0%} converting "
                      f"{(r.conv_deuce if r.conv_deuce is not None else 0):.0%} "
                      f"(n={r.n_deuce}), ad fires {r.att_rate_ad:.0%} converting "
                      f"{(r.conv_ad if r.conv_ad is not None else 0):.0%} "
                      f"(n={r.n_ad})")
            md.append("")
        if not len(het):
            md.append("No pattern shows a court-side difference that survives the "
                      "correction — every gold pattern's pooled estimate stands.")
            md.append("")

    scols = ["player", "gender", "depth", "context", "n", "attempts", "tag",
             "n_deuce", "att_deuce", "win_deuce", "n_ad", "att_ad", "win_ad",
             "att_rate_deuce", "att_rate_ad", "conv_deuce", "conv_ad",
             "p_att", "p_conv", "p_att_holm", "p_conv_holm", "side_diff"]
    scsv = df.copy()
    if len(scsv):
        scsv["context"] = scsv.context.map(_ctx_str)
        scsv = scsv[scols].round(4)
    else:
        scsv = pd.DataFrame(columns=scols)
    scsv.to_csv(PROJECT_ROOT / "reports" / "deep_patterns_side.csv", index=False)
    return md, df, pool_sizes, n_tests


if __name__ == "__main__":
    md, df, pools, n_tests = main()
    md.append("## Verdict")
    md.append("")
    if len(df) >= 20:
        per = df.groupby("player").size()
        md.append(f"**Viable as a gold-star tier.** {len(df)} deep patterns survive the "
                  f"triple gate across {df.player.nunique()} players (median "
                  f"{int(per.median())} per covered player). These are exactly the "
                  "\"only visible with huge coverage\" sequences worth a ⭐ in the "
                  "drawer — shipped via the insights build, shown only when a player "
                  "has them.")
    elif len(df):
        md.append(f"**Marginal.** Only {len(df)} patterns across {df.player.nunique()} "
                  "players survive; a display tier this thin may not be worth the UI.")
    else:
        md.append("**Not viable** — nothing clears an honest bar even at maximal "
                  "coverage.")
    out_csv = df.copy()
    if len(out_csv):
        out_csv["context"] = out_csv.context.map(_ctx_str)
        cols = ["player", "gender", "depth", "context", "n", "attempts", "att_rate",
                "parent_rate", "parent_lift", "conversion", "conv_delta", "tag"]
        out_csv[cols].round(4).to_csv(PROJECT_ROOT / "reports" / "deep_patterns.csv",
                                      index=False)
    (PROJECT_ROOT / "reports" / "deep_patterns.md").write_text("\n".join(md) + "\n")
    print(f"gold rows: {len(df)} across {df.player.nunique() if len(df) else 0} players "
          f"(pool {pools})")
    if len(df):
        print(df.groupby(['gender', 'depth']).size())
        print(f"side heterogeneity: {n_tests} tests, "
              f"{int((df.side_diff != '').sum())} patterns differ by court")
    print("wrote reports/deep_patterns.md + .csv + figure "
          "+ deep_patterns_side.csv")
