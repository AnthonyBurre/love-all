"""Deep (3-4 shot) patterns for heavily-charted players — the gold-star screen.

Run:  python experiments/deep_patterns/run.py

For players with >=10k charted points: mine K=3 and K=4 trigger contexts that
(1) beat their own (K-1)-suffix parent at >=1.3x with an exact binomial p<0.005,
(2) replicate above the parent rate in both match-hash halves (>=15 strokes each),
(3) meet the production support floor (>=60 strokes, >=12 attempts). Survivors are
tagged green/trap by conversion like production triggers. Writes
reports/deep_patterns.{md,csv} + figure.
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
from match_charting_project.shots.notation import parse_point  # noqa: E402

MIN_POINTS = 10_000     # charted points to enter the candidate pool
DEPTHS = (3, 4)         # deep context lengths (production triggers use 2)
MIN_CTX, MIN_ATT = 60, 12          # production support floor
PARENT_LIFT = 1.3       # deep attempt rate must be >= this x its parent's
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
    """Per candidate: base [n,att,win]x2 halves + context tables for K=2..4."""
    base = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    tabs = {k: defaultdict(lambda: [0, 0, 0, 0, 0, 0]) for k in (2, *DEPTHS)}
    sql = (
        "SELECT p.match_id, m.player1, m.player2, p.svr, p.first_serve, p.second_serve, "
        "       p.pt_winner FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for mid, p1, p2, svr, fs, ss, win in batch:
            if p1 not in pool and p2 not in pool:
                continue
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok or len(pt.shots) < 3:
                continue
            toks = point_tokens(pt)
            names = {1: p1, 2: p2}
            h3 = 3 * (zlib.crc32(str(mid).encode()) & 1)
            for i in range(2, len(pt.shots)):
                pl = names[pt.shots[i].hitter]
                if pl not in pool:
                    continue
                term = pt.shots[i].terminal
                att = 1 if term in ("*", "@") else 0
                w = 1 if term == "*" else 0
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
    return base, tabs


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


def _ctx_str(ctx) -> str:
    return " · ".join(pretty(t) for t in ctx)


def main():
    con = connect(read_only=True)
    all_rows = []
    pool_sizes = {}
    for g in ("M", "W"):
        pool = candidates(con, g)
        pool_sizes[g] = len(pool)
        base, tabs = collect(con, g, pool)
        rows = mine(base, tabs)
        for r in rows:
            r["gender"] = g
        all_rows += rows
    con.close()
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
                    md.append(f"- `{_ctx_str(r.context)}` → goes for it "
                              f"{r.att_rate:.0%} vs {r.parent_rate:.0%} without the "
                              f"{'first' if r.depth == 3 else 'first two'} shot(s) "
                              f"({r.parent_lift:.1f}× the parent), converts "
                              f"{r.conversion:.0%} {kind} (n={r.n})")
                md.append("")
    else:
        md.append("**No pattern cleared the gold gates.**")
    md.append("![deep patterns](figures/deep_patterns.png)")
    md.append("")
    return md, df, pool_sizes


if __name__ == "__main__":
    md, df, pools = main()
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
    print("wrote reports/deep_patterns.md + .csv + figure")
