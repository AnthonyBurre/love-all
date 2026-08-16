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
Discovery itself stays pooled.

A shadow pass then re-runs the entire gold screen on the narrower *finishing
shot* numerator (winner + own unforced error, no induced forced errors) from the
same counts, and reports how much the survivor set moves. Writes
reports/deep_patterns.{md,csv}, reports/deep_patterns_side.csv,
reports/deep_patterns_numerator.csv + figure.
"""

import sys
import zlib
from collections import defaultdict
from math import comb, exp, lgamma, log, log1p
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
Q_FDR = 0.10            # Benjamini-Hochberg false-discovery rate, within player

# Counter layout. Every context tallies both numerators at once so the whole
# gold screen can be re-run on the narrower one without a second pass over the
# points: N strokes, then (attempts, converted) for each reading.
N, ATT, WIN, FATT, FWIN = 0, 1, 2, 3, 4
HALF = 5                # slots per match-hash half; half 1 starts at index HALF
NUMERATORS = {          # label -> (attempt slot, converted slot)
    "aggressive": (ATT, WIN),    # winner + own unforced + induced forced (shipped)
    "finishing": (FATT, FWIN),   # winner + own unforced only (pre-2026-08-05)
}
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
    """Per candidate: base [n,att,win,fatt,fwin]x2 halves + context tables for K=2..4.

    The ``f*`` slots are the shadow tally: the same strokes scored under the
    narrower *finishing shot* reading (winner + own unforced error, no induced
    forced errors), so ``mine`` can run the identical gold screen twice.

    Also builds ``side_tabs``: for each deep context, the [n, att, win] counts of
    its *opening-touching* occurrences — those whose K-shot window reaches into
    the first four plies (serve, return, serve+1, return+1), where the notation
    is side-relative — split by deuce/ad. These feed the heterogeneity pass over
    the pooled gold survivors; mid-rally occurrences are never side-split.
    """
    base = defaultdict(lambda: [0] * (2 * HALF))
    tabs = {k: defaultdict(lambda: [0] * (2 * HALF)) for k in (2, *DEPTHS)}
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
            h = HALF * (zlib.crc32(str(mid).encode()) & 1)
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
                # shadow tally: the narrower reading drops the induced forced
                # error from both the numerator and what counts as paying off.
                fatt = _w + _e
                fw = _w
                b = base[pl]
                b[h + N] += 1
                b[h + ATT] += att
                b[h + WIN] += w
                b[h + FATT] += fatt
                b[h + FWIN] += fw
                for k in tabs:
                    if i >= k:
                        c = tabs[k][(pl, tuple(toks[i - k:i]))]
                        c[h + N] += 1
                        c[h + ATT] += att
                        c[h + WIN] += w
                        c[h + FATT] += fatt
                        c[h + FWIN] += fw
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
    """P(X >= k) for X ~ Binomial(n, p), summed outward from the mode.

    The straightforward ``sum(comb(n, j) * p**j * ...)`` is exact and fine while this
    is only ever called on patterns that already cleared a lift gate; it overflows the
    moment it is called on every context that has a parent, because ``comb`` on a few
    thousand strokes is an integer far too large to convert to a float. Walking out
    from the mode instead keeps every term inside double range: the largest term is
    ``pmf(mode)``, which is about ``1/sqrt(2*pi*n*p*q)`` and cannot underflow, and each
    neighbour follows from the one before by a ratio. Dividing by the mass actually
    accumulated makes the result insensitive to where the walks are cut off.
    """
    if p <= 0:
        return 0.0 if k > 0 else 1.0
    if p >= 1:
        return 1.0
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    mode = min(n, max(0, int((n + 1) * p)))
    pm = exp(lgamma(n + 1) - lgamma(mode + 1) - lgamma(n - mode + 1)
             + mode * log(p) + (n - mode) * log1p(-p))
    r = p / (1.0 - p)
    total = pm
    tail = pm if mode >= k else 0.0
    # Both walks stop once the remaining mass cannot move either figure. The tail gets
    # its own test: cutting off when a term is negligible against `total` alone would
    # flatten a genuinely tiny tail to zero before its first term was ever reached,
    # which is the p-values of the very patterns this screen most wants to rank.
    def spent(term, tail):
        return term < total * 1e-18 and (tail > 0.0 and term < tail * 1e-16)

    term = pm
    for j in range(mode, n):                      # upward from the mode
        term *= (n - j) / (j + 1) * r
        total += term
        if j + 1 >= k:
            tail += term
        if spent(term, tail):
            break
    term = pm
    for j in range(mode, 0, -1):                  # downward from the mode
        term *= j / ((n - j + 1) * r)
        total += term
        if j - 1 >= k:
            tail += term
        if spent(term, tail):
            break
    return min(1.0, tail / total)


def score(base, tabs, k: int, key: tuple, numerator: str):
    """Run the three gold gates over one (player, context) under one numerator.

    Returns ``(row, None, p)`` when it earns gold, else ``(None, gate, p)`` naming
    the first gate it failed. The comparison pass needs the failure reason and,
    for a binomial failure, how far past the threshold it landed — a p of 0.006
    and a p of 0.4 are very different kinds of miss. ``p`` is None when the
    pattern failed before the test was reached.
    """
    ai, wi = NUMERATORS[numerator]
    c = tabs[k].get(key)
    if c is None:
        return None, "absent", None
    pl, ctx = key
    n = c[N] + c[HALF + N]
    att = c[ai] + c[HALF + ai]
    win = c[wi] + c[HALF + wi]
    if n < MIN_CTX or att < MIN_ATT:
        return None, "support", None
    parent = tabs[k - 1].get((pl, ctx[1:]))
    if not parent:
        return None, "no parent", None
    pn, patt = parent[N] + parent[HALF + N], parent[ai] + parent[HALF + ai]
    if pn == 0 or patt == 0:
        return None, "no parent", None
    p_rate = patt / pn
    # The tail is computed before the lift gate rather than after it, so every context
    # that got as far as having a parent to be measured against carries a p — including
    # the ones the lift gate turns away. Those are not free: the screen looked at them,
    # and leaving them out of the multiplicity family would count a search over hundreds
    # of contexts as a search over the handful that happened to clear 1.3x. See mine().
    pval = binom_tail(att, n, p_rate)
    if att / n < PARENT_LIFT * p_rate:
        return None, "lift", pval
    if pval >= P_MAX:
        return None, "binomial", pval
    if not (c[N] >= HALF_N and c[HALF + N] >= HALF_N
            and c[ai] / c[N] > p_rate and c[HALF + ai] / c[HALF + N] > p_rate):
        return None, "replication", pval
    b = base[pl]
    b_att, b_win = b[ai] + b[HALF + ai], b[wi] + b[HALF + wi]
    base_conv = b_win / b_att if b_att else 0.0
    conv = win / att
    return {
        "player": pl, "depth": k, "context": ctx, "n": n, "attempts": att,
        "att_rate": att / n, "parent_rate": p_rate,
        "parent_lift": (att / n) / p_rate,
        "conversion": conv, "conv_delta": conv - base_conv,
        "tag": "green" if conv >= base_conv else "trap",
        "strokes": b[N] + b[HALF + N],
    }, None, pval


def mine(base, tabs, numerator: str = "aggressive") -> list:
    """Gold survivors under one numerator, false-discovery controlled within player.

    ``numerator`` picks which tally the whole screen runs on. Every gate reads
    the same slots, so passing ``"finishing"`` reproduces the pre-2026-08-05
    screen exactly rather than approximating it.

    The binomial test in ``score`` is one test, and it is not run once. A heavily
    charted player puts hundreds of contexts through it — 615 for Federer, 569 for
    Djokovic, 406 for Nadal — so a raw p<0.005 threshold expects about three chance
    survivors from Federer alone, against the thirteen he posts. Scaled over the pool
    that is roughly 35-45 false positives among the ~72 patterns the screen used to
    return: about half.

    The replication gate below the test does not fix this, and it was doing far less
    work than the README claimed. It re-uses the same pooled data that selected the
    pattern, so once the pooled estimate sits a few standard errors above the parent
    rate, both halves clear it almost automatically — it rejected none of the 35
    patterns that cleared the binomial test across a re-run of eight players.

    So the p-values are Benjamini-Hochberg adjusted across each player's *own*
    candidate pool — every context of theirs that reached the binomial test, whether
    it passed or failed — and only patterns clearing q=0.10 after that are gold. BH
    within player is the right family: the claim on the panel is "this player has this
    tendency", so the multiplicity that matters is how many tendencies were tried on
    that player. It is also strictly tighter than the old fixed threshold at these pool
    sizes, so every survivor is a pattern the previous screen would also have returned.
    """
    tested = defaultdict(list)      # player -> [(pval, row_or_None)]
    for k in DEPTHS:
        for key in tabs[k]:
            row, _gate, pval = score(base, tabs, k, key, numerator)
            if pval is not None:    # reached the binomial test: a real candidate
                tested[key[0]].append((pval, row))
    out = []
    for _pl, items in tested.items():
        adj = bh([p for p, _ in items])
        for (pval, row), q in zip(items, adj):
            if row is not None and q <= Q_FDR:
                row["p_raw"], row["p_bh"], row["n_candidates"] = pval, q, len(items)
                out.append(row)
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


def bh(pvals: list) -> list:
    """Benjamini-Hochberg adjusted p-values (step-up), returned in the input order."""
    m = len(pvals)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: pvals[i], reverse=True)
    adj, running = [1.0] * m, 1.0
    for rank, i in enumerate(order):
        running = min(running, min(1.0, m / (m - rank) * pvals[i]))
        adj[i] = running
    return adj


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


def _key(r) -> tuple:
    return (r["gender"], r["depth"], r["player"], r["context"])


def numerator_comparison(shipped: list, shadow: list, data_by_gender: dict) -> list:
    """How the gold set moves when the numerator widens.

    ``shot_triggers`` established that the wider reading is more reliable at K=2,
    on contexts with far more support than these. That evidence does not carry
    to K=3/4 by itself: widening moves the child rate *and* the parent rate it is
    measured against, so the 1.3x lift gate can get harder even as the support
    and binomial gates get easier. This compares the two survivor sets directly
    and, for every pattern only one numerator finds, names the gate the other
    one failed.
    """
    ship = {_key(r): r for r in shipped}
    shad = {_key(r): r for r in shadow}
    both = ship.keys() & shad.keys()
    ship_only, shad_only = ship.keys() - shad.keys(), shad.keys() - ship.keys()

    why = {"ship_only": defaultdict(int), "shad_only": defaultdict(int)}
    pvals = {"ship_only": [], "shad_only": []}
    for keys, other, bucket in ((ship_only, "finishing", "ship_only"),
                                (shad_only, "aggressive", "shad_only")):
        for g, k, pl, ctx in keys:
            base, tabs = data_by_gender[g]
            _, gate, p = score(base, tabs, k, (pl, ctx), other)
            why[bucket][gate] += 1
            if gate == "binomial":
                pvals[bucket].append(p)

    flips = sum(1 for k in both if ship[k]["tag"] != shad[k]["tag"])
    union = len(both) + len(ship_only) + len(shad_only)

    md = ["## Does the numerator change the gold set?", ""]
    md.append(
        "The switch from the narrower **finishing shot** reading (winner + own "
        "unforced error) to the **aggressive shot** reading shipped here (which "
        "also credits a shot that forced the reply into an error) was validated "
        "in `shot_triggers` on K=2 contexts. Nothing about that test covers the "
        "K=3/4 patterns mined here — those contexts are rarer and sit nearer "
        "their support floor. So the whole gold screen is re-run on the narrower "
        "tally from the same stroke-by-stroke counts, and the two survivor sets "
        "are compared. Widening pulls the gates in opposite directions: more "
        "events per context makes the support and binomial gates easier, while "
        "raising the parent rate the child must beat by "
        f"{PARENT_LIFT}x makes the lift gate harder.")
    md.append("")
    md.append("| | aggressive (shipped) | finishing (narrow) |")
    md.append("|---|--:|--:|")
    agg_k = {k: sum(1 for r in shipped if r["depth"] == k) for k in DEPTHS}
    fin_k = {k: sum(1 for r in shadow if r["depth"] == k) for k in DEPTHS}
    md.append(f"| gold patterns | {len(shipped)} | {len(shadow)} |")
    for k in DEPTHS:
        md.append(f"| K={k} | {agg_k[k]} | {fin_k[k]} |")
    md.append(f"| players with ≥1 | {len({r['player'] for r in shipped})} | "
              f"{len({r['player'] for r in shadow})} |")
    md.append("")
    md.append(f"**Overlap: {len(both)} of {union} patterns in the union are found by "
              f"both** ({len(both) / union:.0%} Jaccard). {len(ship_only)} are "
              f"aggressive-only, {len(shad_only)} finishing-only.")
    md.append("")
    for keys, bucket, who, other in (
            (ship_only, "ship_only", "narrow", "aggressive-only"),
            (shad_only, "shad_only", "wide", "finishing-only")):
        if not keys:
            continue
        md.append(f"Gate the {who} numerator failed on the {other} patterns: "
                  + ", ".join(f"**{g}** ({n})" for g, n in
                              sorted(why[bucket].items(), key=lambda x: -x[1])) + ".")
        ps = sorted(pvals[bucket])
        if ps:
            near = sum(1 for p in ps if p < 10 * P_MAX)
            verdict = ("mostly a power difference at the cutoff rather than a "
                       "different story about the pattern"
                       if near > len(ps) / 2 else
                       "these are decisive misses, not threshold accidents")
            md.append(f"Of those {len(ps)} binomial failures, {near} land within 10× "
                      f"the p<{P_MAX} threshold (median p={ps[len(ps) // 2]:.3f}) — "
                      f"{verdict}.")
        md.append("")
    if both:
        md.append(f"Among the {len(both)} shared patterns, the green/trap tag flips on "
                  f"**{flips}** ({flips / len(both):.0%}) — the numerator decides "
                  "which shots count as paying off, so a pattern can survive both "
                  "screens and still be read differently.")
        md.append("")
    return md


def main():
    con = connect(read_only=True)
    all_rows = []
    shadow_rows = []
    side_tabs_by_gender = {}
    data_by_gender = {}
    pool_sizes = {}
    for g in ("M", "W"):
        pool = candidates(con, g)
        pool_sizes[g] = len(pool)
        base, tabs, side_tabs = collect(con, g, pool)
        side_tabs_by_gender[g] = side_tabs
        data_by_gender[g] = (base, tabs)
        for numerator, sink in (("aggressive", all_rows), ("finishing", shadow_rows)):
            rows = mine(base, tabs, numerator)
            for r in rows:
                r["gender"] = g
            sink += rows
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
              f"binomial p<{P_MAX}), survives Benjamini-Hochberg at q={Q_FDR:g} across "
              "every one of that player's own candidate contexts, replicates above the "
              "parent in both match-hash halves, and meets the production support "
              f"floor. Candidate pool: {pool_sizes['M']} men + {pool_sizes['W']} women "
              f"with ≥{MIN_POINTS:,} charted points.*")
    md.append("")
    md.append("The false-discovery correction is the gate that does the work here, and "
              "it was missing until 2026-08-16. A heavily charted player puts hundreds "
              "of contexts through the binomial test — the per-player candidate counts "
              "are in `deep_patterns.csv` — so a fixed p<0.005 expected a few chance "
              "survivors per player and returned 72 patterns across 28 players where "
              "it now returns "
              f"{len(df)} across {df.player.nunique() if len(df) else 0}. The "
              "both-halves replication gate below the test does not substitute for it: "
              "it re-reads the same pooled counts that selected the pattern, so it "
              "rejects almost nothing.")
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

    # -- numerator shadow pass ---------------------------------------------------
    md += numerator_comparison(all_rows, shadow_rows, data_by_gender)

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

    # per-pattern membership for the shadow pass, so the comparison is auditable
    ship, shad = {_key(r) for r in all_rows}, {_key(r) for r in shadow_rows}
    ncsv = pd.DataFrame([
        {"player": pl, "gender": g, "depth": k, "context": _ctx_str(ctx),
         "aggressive_gold": key in ship, "finishing_gold": key in shad}
        for key in sorted(ship | shad, key=lambda x: (x[0], x[2], x[1]))
        for g, k, pl, ctx in [key]
    ], columns=["player", "gender", "depth", "context",
                "aggressive_gold", "finishing_gold"])
    ncsv.to_csv(PROJECT_ROOT / "reports" / "deep_patterns_numerator.csv", index=False)
    return md, df, pool_sizes, n_tests, shadow_rows


if __name__ == "__main__":
    md, df, pools, n_tests, shadow = main()
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
        # p_raw/p_bh/n_candidates ride along so the correction is auditable from the
        # CSV: a reader can see both what the pattern scored and how many of this
        # player's contexts it was picked out of.
        cols = ["player", "gender", "depth", "context", "n", "attempts", "att_rate",
                "parent_rate", "parent_lift", "conversion", "conv_delta", "tag",
                "p_raw", "p_bh", "n_candidates"]
        out_csv[cols].round(4).to_csv(PROJECT_ROOT / "reports" / "deep_patterns.csv",
                                      index=False)
    (PROJECT_ROOT / "reports" / "deep_patterns.md").write_text("\n".join(md) + "\n")
    print(f"gold rows: {len(df)} across {df.player.nunique() if len(df) else 0} players "
          f"(pool {pools})")
    if len(df):
        print(df.groupby(['gender', 'depth']).size())
        print(f"side heterogeneity: {n_tests} tests, "
              f"{int((df.side_diff != '').sum())} patterns differ by court")
    print(f"numerator shadow pass: {len(df)} gold under aggressive vs "
          f"{len(shadow)} under finishing")
    print("wrote reports/deep_patterns.md + .csv + figure "
          "+ deep_patterns_side.csv + deep_patterns_numerator.csv")
