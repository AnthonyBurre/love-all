"""Shot-making triggers: aggressive shot frequency and conversion per lead-up.

Run:  python experiments/shot_triggers/run.py

Recasts shot_patterns' separate winner/error books as one decision (the aggressive
shot) plus execution (conversion). An **aggressive shot** is a stroke that ends the
point on the player's own racquet (winner, own unforced error) or forces the reply
into an error; **aggressive shot frequency** is how often a rally stroke is one, and
**conversion** is the share that paid (winner or induced forced error). Per player:
trigger contexts (frequency lift), green lights vs traps (conversion vs their own
baseline), the winner-vs-error context correlation (are the two books the same
book?), and a pattern-immunity score (frequency overdispersion vs binomial noise).

A section near the end justifies the numerator against the narrower **finishing
shot frequency** (winner + own unforced error, no induced forced errors) that this
experiment used through 2026-08-05, on split-half reliability.

The pooled contexts above average over the serve side. A final section splits the
first-four-ply openings — the return, serve+1 and return+1 — by deuce/ad court,
since a wide serve opens opposite wings on the two sides; everything deeper in the
rally stays pooled. Each opening context is scored against the player's own norm
for that same shot and side.

Writes reports/shot_triggers.md, reports/shot_triggers.csv,
reports/shot_triggers_openings.csv, reports/figures/shot_triggers.png and
reports/figures/shot_triggers_definitions.png.
"""

import sys
import zlib
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
from tokens import hand_map, point_tokens, pretty  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import aggressive_shot, parse_point  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402
from match_charting_project.stats import bh, binom_tail  # noqa: E402

K = 2               # context = the K shots before the player's stroke
MIN_SHOTS = 4000    # a player needs this many contextful strokes to be ranked
MIN_CTX = 60        # a context needs this many of the player's strokes
MIN_ATT = 12        # ...and this many aggressive shots for conversion to mean anything
PHI_MIN_CTX = 20    # contexts needed for the immunity (dispersion) score
TRIGGER_LIFT = 1.5  # frequency lift that counts as a trigger context
TOP = 4
GLABEL = {"M": "Men", "W": "Women"}
MARQUEE = {
    "M": ["Roger Federer", "Novak Djokovic", "Rafael Nadal", "Pete Sampras", "Andre Agassi"],
    "W": ["Serena Williams", "Iga Swiatek", "Martina Navratilova", "Steffi Graf"],
}


# Opening plies to split by serve side: the aggressive shot sits in the first four
# plies (serve, return, and the +1 shots), so context + shot stay inside the opening.
# (stroke index 0-based, anchor label, serving/returning role). The context is the
# up-to-K prior strokes, so every one of these stays within plies 1-4.
OPEN_ANCHORS = ((1, "return", "return"),      # returner's ball, ctx = (serve,)
                (2, "serve+1", "serve"),      # server's +1,      ctx = (serve, return)
                (3, "return+1", "return"))    # returner's +1,    ctx = (return, serve+1)
OPEN_MIN_BASE = 200   # per (player, side, anchor): strokes needed for a stable baseline
MIN_HALF = 25         # strokes a context needs in *each* half to enter the split-half test
MIN_FOLD_ATT = 6      # aggressive shots a context needs in a fold to be tested or confirmed there
Q_FDR = 0.10          # Benjamini-Hochberg false-discovery rate, within player


def collect(con, gender: str, hands: dict) -> "tuple[dict, dict]":
    """Pooled per-player context tables (all plies) plus side-split opening tables.

    ``acc``: player -> {n, w, e, f, ctx:{context: [n, w, e, f]}, half:{(h, context):
    [n, w, e, f]}} over every ply, sides pooled. ``half`` buckets the same counts by
    a random split of the player's matches, which is what the definitions comparison
    correlates across; matches (not points) are the split unit so a charter's
    judgment lands wholly on one side.
    ``openings``: (player, side, anchor) -> {base:[n,w,e,f], ctx:{context:[n,w,e,f]}}
    for the first-four-ply aggressive shots only, split by deuce/ad.

    Cues are keyed in the *profiled player's* frame: for a left-hander every court third
    in the lead-up is mirrored, so a cue names the shot rather than the half of the court
    it landed in. The direction codes are the codebook's, which name fixed thirds by the
    right-hander convention, so without this a lefty's cue string describes the mirror
    image of what a right-hander's identical string describes — and the panel prints the
    two as though they were one pattern.

    Mirrored by the striker rather than by each shot's own hitter, because the cue
    alternates hitters and a player's opponents are a mix of both hands; mirroring per
    hitter would merge physically different opponent balls into one bucket. The whole
    lead-up reads from the profiled player's side of the net, matching what
    ``court_response`` does with hand-relative zones and what ``deep_patterns`` does with
    the same tokens.

    This changes no statistic. Every figure here — the lift against the player's own
    own fold's rate, the conversion against that fold's own trigger class, the
    cross-validation, the FDR family — is computed within one player, so mirroring re-keys a
    lefty's whole table consistently and every count comes out identical. It is a
    labelling fix, and only a labelling fix.
    """
    acc: dict = defaultdict(lambda: {"n": 0, "w": 0, "e": 0, "f": 0,
                                     "ctx": defaultdict(lambda: [0, 0, 0, 0]),
                                     "half": defaultdict(lambda: [0, 0, 0, 0])})
    openings: dict = defaultdict(lambda: {"base": [0, 0, 0, 0],
                                          "ctx": defaultdict(lambda: [0, 0, 0, 0])})
    sql = (
        "SELECT m.match_id, m.player1, m.player2, p.svr, p.pts, p.first_serve, "
        "       p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for mid, p1, p2, svr, pts, fs, ss, win in batch:
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            names = {1: p1, 2: p2}
            # One token stream per striker, in that striker's own frame. Passing both
            # hitter numbers mirrors every rally shot in the point; the two streams are
            # the same object whenever the strikers share a hand, which is most points.
            plain = point_tokens(pt)
            lefty = {w: hands.get(names[w]) == "L" for w in (1, 2)}
            mirrored = point_tokens(pt, (1, 2)) if (lefty[1] or lefty[2]) else plain
            toks_for = {w: (mirrored if lefty[w] else plain) for w in (1, 2)}
            n_sh = len(pt.shots)
            half = zlib.crc32(str(mid).encode()) & 1   # stable across runs

            # Side-split openings first — these include short points that end on
            # the return (rally <= K), which the pooled loop below skips.
            side = serve_side(pts)
            if side in ("deuce", "ad"):
                for idx, anchor, _role in OPEN_ANCHORS:
                    if idx >= n_sh:
                        break
                    s = pt.shots[idx]
                    rec = openings[(names[s.hitter], side, anchor)]
                    ctx = tuple(toks_for[s.hitter][max(0, idx - K):idx])
                    w, e, f = aggressive_shot(pt.shots, idx, n_sh)
                    for bucket in (rec["base"], rec["ctx"][ctx]):
                        bucket[0] += 1
                        bucket[1] += w
                        bucket[2] += e
                        bucket[3] += f

            if n_sh <= K:
                continue
            for i in range(K, n_sh):
                a = acc[names[pt.shots[i].hitter]]
                ctx = tuple(toks_for[pt.shots[i].hitter][i - K:i])
                w, e, f = aggressive_shot(pt.shots, i, n_sh)
                a["n"] += 1
                a["w"] += w
                a["e"] += e
                a["f"] += f
                for bucket in (a["ctx"][ctx], a["half"][(half, ctx)]):
                    bucket[0] += 1
                    bucket[1] += w
                    bucket[2] += e
                    bucket[3] += f
    return acc, openings


def context_table(a: dict) -> "pd.DataFrame":
    """Per qualifying context: aggressive shot frequency/lift, conversion, w/e rates.

    Carries the narrower *finishing shot* columns (``fin_*``: winner + own unforced
    error, no induced forced errors) alongside, so the definitions comparison can be
    computed from the same tables the report is built from rather than a second pass.
    """
    agg = a["w"] + a["e"] + a["f"]
    fin = a["w"] + a["e"]
    base_att = agg / a["n"]
    base_conv = (a["w"] + a["f"]) / agg if agg else 0.0
    base_fin = fin / a["n"]
    base_fin_conv = a["w"] / fin if fin else 0.0
    rows = []
    for ctx, (n, w, e, f) in a["ctx"].items():
        if n < MIN_CTX:
            continue
        att, fatt = w + e + f, w + e
        rows.append({
            "context": ctx, "n": n, "attempts": att,
            "att_rate": att / n, "att_lift": (att / n) / base_att if base_att else 0.0,
            "conv": (w + f) / att if att else np.nan,
            "w_rate": w / n, "e_rate": e / n, "f_rate": f / n,
            "fin_attempts": fatt, "fin_rate": fatt / n,
            "fin_lift": (fatt / n) / base_fin if base_fin else 0.0,
            "fin_conv": w / fatt if fatt else np.nan,
        })
    df = pd.DataFrame(rows)
    df.attrs["base_att"] = base_att
    df.attrs["base_conv"] = base_conv
    df.attrs["base_fin"] = base_fin
    df.attrs["base_fin_conv"] = base_fin_conv
    return df


def we_correlation(df: "pd.DataFrame") -> float:
    """Across contexts: do winner rate and unforced rate rise together?"""
    if len(df) < PHI_MIN_CTX:
        return np.nan
    return float(np.corrcoef(df.w_rate, df.e_rate)[0, 1])


def dispersion(df: "pd.DataFrame") -> float:
    """sigma: true between-context sd of aggressive shot frequency, in prob. points.

    Beta-binomial method of moments — the binomial noise floor is subtracted,
    so heavily-charted players aren't penalized for having tighter estimates:
    E[(k - n*p)^2] = n*p*q + n*(n-1)*sigma^2  summed over contexts.
    0 = the decision looks context-blind; large = strongly cue-driven.
    """
    if len(df) < PHI_MIN_CTX:
        return np.nan
    p = df.attempts.sum() / df.n.sum()
    excess = ((df.attempts - df.n * p) ** 2 - df.n * p * (1 - p)).sum()
    denom = (df.n * (df.n - 1)).sum()
    return float(np.sqrt(max(excess / denom, 0.0)))


def fold_totals(a: dict) -> tuple:
    """Per-fold player totals and per-fold per-context counts, as [n, w, e, f].

    Every contextful stroke is accumulated into exactly one ``(half, context)`` bucket,
    so summing those buckets recovers the player's own totals within each half — no
    second pass and no extra accumulator.
    """
    tot = {0: [0, 0, 0, 0], 1: [0, 0, 0, 0]}
    per = {0: {}, 1: {}}
    for (h, ctx), v in a["half"].items():
        for i in range(4):
            tot[h][i] += v[i]
        per[h][ctx] = v
    return tot, per


# The two readings of "went for it", as functions of a [n, w, e, f] bucket. ``att`` is
# what counts as an aggressive shot, ``win`` is what counts as having paid off.
NUMERATORS = {
    "":     (lambda v: v[1] + v[2] + v[3], lambda v: v[1] + v[3]),   # aggressive (shipped)
    "fin_": (lambda v: v[1] + v[2],        lambda v: v[1]),          # finishing (shadow)
}


def tag_contexts(df: "pd.DataFrame", a: dict) -> "pd.DataFrame":
    """Label each context green / trap / neutral by two-fold cross-validation.

    A cue makes two claims — this lead-up raises the player's aggressive shot frequency,
    and what they go for from it converts better or worse than their other cues do — and
    both have to survive being tested on data that had no say in picking the cue.

    The player's matches are split in half by hash. Each half takes a turn as the
    **discovery** fold: the frequency lift, the significance test and the per-player FDR
    correction all run inside it, and nothing outside it is consulted. The cue is then
    **validated** on the other half, which was not involved in selecting it: the lift has
    to still point the same way there, and the tag is read off the conversion sign *in
    the validation fold*, against that fold's own trigger-class mean. Both directions are
    run, and a cue ships if either survives.

    This replaced a pooled screen with a both-halves consistency check bolted on, which
    was circular: the reference and the candidate lift were computed over all the
    player's matches, and the two halves it then "confirmed" against were subsets of the
    data that had just selected it. It was also strictly harsher than cross-validation
    without buying anything for the strictness — it demanded agreement from both halves
    at once, where running each half as its own experiment asks each of them a question
    it can actually answer independently.

    The figures reported are the held-out ones. When a single direction confirms, the
    cue's rate, lift and conversion come from the validation fold alone; when both
    confirm, the pooled figures are the attempts-weighted mean of two independently clean
    estimates and are used as-is. Either way the number on the card was measured on data
    that did not choose the cue, which also removes the selection inflation that a
    top-of-the-ranking effect size otherwise carries.
    """
    out = df.copy()
    out.attrs = dict(df.attrs)
    tot, per = fold_totals(a)
    ctx_index = {c: i for i, c in enumerate(out["context"])}

    for pre, (att_of, win_of) in NUMERATORS.items():
        n_rows = len(out)
        tag = ["neutral"] * n_rows
        # Held-out display values, filled in only for confirmed cues.
        d_rate, d_lift, d_conv, d_delta = ([np.nan] * n_rows for _ in range(4))
        d_n, d_att = ([0] * n_rows for _ in range(2))

        # Per-fold player baseline and per-fold per-context figures.
        base = {}
        fold = {0: {}, 1: {}}
        for h in (0, 1):
            bn, batt = tot[h][0], att_of(tot[h])
            base[h] = batt / bn if bn else 0.0
            for ctx, v in per[h].items():
                if ctx not in ctx_index:
                    continue
                n, att = v[0], att_of(v)
                fold[h][ctx] = {
                    "n": n, "att": att,
                    "rate": att / n if n else 0.0,
                    "lift": (att / n) / base[h] if n and base[h] else 0.0,
                    "conv": win_of(v) / att if att else np.nan,
                }

        # Each fold's own trigger-class mean: the attempts-weighted conversion across the
        # cues that fold calls triggers. Computed inside the fold so that a validation
        # fold's reference never borrows from the fold that did the selecting.
        klass = {}
        for h in (0, 1):
            num = den = 0.0
            for c in fold[h].values():
                if c["lift"] >= TRIGGER_LIFT and c["att"] >= MIN_FOLD_ATT and np.isfinite(c["conv"]):
                    num += c["conv"] * c["att"]
                    den += c["att"]
            klass[h] = num / den if den else np.nan

        # A player can have no qualifying trigger in either fold, leaving both class
        # means undefined; nanmean over that is an empty slice, so guard rather than warn.
        finite = [v for v in klass.values() if np.isfinite(v)]
        out.attrs[f"{pre}base_trig_conv"] = float(np.mean(finite)) if finite else np.nan
        confirmed = {}          # context -> list of (tag, validation fold)
        for disc, val in ((0, 1), (1, 0)):
            if not np.isfinite(klass[val]) or base[disc] <= 0:
                continue
            # The correction family is every context this fold could test at all.
            fam = [c for c in ctx_index
                   if c in fold[disc] and fold[disc][c]["att"] >= MIN_FOLD_ATT]
            if not fam:
                continue
            pv = [binom_tail(int(fold[disc][c]["att"]), int(fold[disc][c]["n"]), base[disc])
                  for c in fam]
            for c, q in zip(fam, bh(pv)):
                d, v = fold[disc][c], fold[val].get(c)
                if q > Q_FDR or d["lift"] < TRIGGER_LIFT:
                    continue
                if not v or v["att"] < MIN_FOLD_ATT or not np.isfinite(v["conv"]):
                    continue
                if v["lift"] <= 1.0:        # the frequency claim has to survive too
                    continue
                confirmed.setdefault(c, []).append(
                    ("green" if v["conv"] >= klass[val] else "trap", val))

        for c, hits in confirmed.items():
            tags = {t for t, _ in hits}
            if len(tags) > 1:
                continue            # the two directions disagree: not a finding
            i = ctx_index[c]
            tag[i] = hits[0][0]
            if len(hits) == 2:      # both clean; pooled is the mean of two clean halves
                d_n[i], d_att[i] = int(out.at[i, "n"]), int(out.at[i, f"{pre}attempts"])
                d_rate[i] = out.at[i, f"{pre}rate" if pre else "att_rate"]
                d_lift[i] = out.at[i, f"{pre}lift" if pre else "att_lift"]
                d_conv[i] = out.at[i, f"{pre}conv"]
            else:
                v = fold[hits[0][1]][c]
                d_n[i], d_att[i] = int(v["n"]), int(v["att"])
                d_rate[i], d_lift[i], d_conv[i] = v["rate"], v["lift"], v["conv"]
            # The reference is attempts-weighted across the confirming folds, matching
            # how the displayed conversion is pooled across them. Equal-weighting the two
            # class means instead lets a cue whose sign held in *both* folds come out with
            # a delta pointing the other way, purely from the weighting mismatch — which
            # is a tag and a number contradicting each other on the card.
            wsum = sum(fold[v][c]["att"] for _, v in hits)
            ref = sum(klass[v] * fold[v][c]["att"] for _, v in hits) / wsum
            d_delta[i] = d_conv[i] - ref

        out[f"{pre}tag"] = tag
        out[f"{pre}conv_delta"] = d_delta
        out[f"{pre}oos_n"] = d_n
        out[f"{pre}oos_attempts"] = d_att
        # The shipped figures are the held-out ones wherever a cue is tagged; untagged
        # rows keep their pooled values, which nothing reads.
        for col, vals in ((f"{pre}rate" if pre else "att_rate", d_rate),
                          (f"{pre}lift" if pre else "att_lift", d_lift),
                          (f"{pre}conv", d_conv)):
            out[col] = [vals[i] if tag[i] != "neutral" else out.at[i, col]
                        for i in range(n_rows)]
        for col, vals in ((("n" if pre == "" else f"{pre}n"), d_n),
                          (f"{pre}attempts", d_att)):
            if col in out.columns:
                out[col] = [vals[i] if tag[i] != "neutral" else out.at[i, col]
                            for i in range(n_rows)]
    return out


def _ctx_str(ctx) -> str:
    return " · ".join(pretty(t) for t in ctx)


def player_block(md, player, df):
    base_att, base_conv = df.attrs["base_att"], df.attrs["base_conv"]
    trig_conv = df.attrs.get("base_trig_conv", float("nan"))
    n_all = int(df.n.sum())
    md.append(f"### {player}")
    md.append(f"*aggressive on {base_att:.1%} of strokes, converting {base_conv:.0%}; "
              f"across their trigger cues, {trig_conv:.0%}; {n_all:,} contextful strokes*\n")
    trig = df[df.tag != "neutral"].sort_values("att_lift", ascending=False)
    md.append("**Trigger sequences** (lead-ups that most raise the frequency):")
    for r in trig.head(TOP).itertuples():
        kind = "✅ converts" if r.tag == "green" else "⚠️ trap"
        md.append(f"- `{_ctx_str(r.context)}` → aggressive {r.att_rate:.0%} "
                  f"({r.att_lift:.1f}×), converts {r.conv:.0%} "
                  f"({r.conv_delta:+.0%} vs their other cues) {kind} "
                  f"(n={r.n}, {r.attempts} attempts)")
    traps = df[df.tag == "trap"].sort_values("conv_delta")
    if len(traps):
        md.append("\n**Worst traps** (pulled into aggressive shots they don't convert):")
        for r in traps.head(3).itertuples():
            md.append(f"- `{_ctx_str(r.context)}` → aggressive {r.att_lift:.1f}× their norm "
                      f"but converts only {r.conv:.0%} vs {trig_conv:.0%} across their "
                      f"other cues (n={r.n}, {r.attempts} attempts)")
    else:
        md.append("\n**No trap contexts** — no cue that raises the frequency was found "
                  "to convert below the rest of their cues when tested on matches that "
                  "had no part in selecting it. Unbaitable (at this resolution).")
    md.append("")


def split_half_pairs(a: dict) -> "list":
    """Per context, the two definitions' frequencies measured on each half separately.

    A context only qualifies where both halves carry ``MIN_HALF`` strokes, so the
    comparison is never between a well-measured half and a rumour. Correlating these
    across contexts estimates what share of the apparent between-context spread is
    real: it is the reliability of the statistic, and it is the test that decides
    which numerator to ship.
    """
    h0 = {c: v for (h, c), v in a["half"].items() if h == 0 and v[0] >= MIN_HALF}
    h1 = {c: v for (h, c), v in a["half"].items() if h == 1 and v[0] >= MIN_HALF}
    pairs = []
    for ctx in h0.keys() & h1.keys():
        n0, w0, e0, f0 = h0[ctx]
        n1, w1, e1, f1 = h1[ctx]
        pairs.append({
            "agg0": (w0 + e0 + f0) / n0, "agg1": (w1 + e1 + f1) / n1,
            "fin0": (w0 + e0) / n0, "fin1": (w1 + e1) / n1,
        })
    return pairs


def definition_block(md: list, defs: "pd.DataFrame", pairs: "pd.DataFrame",
                     flips: "pd.DataFrame") -> "pd.DataFrame":
    """Report section: why the numerator counts induced forced errors.

    Returns the per-player reliability frame so the figure can draw it.
    """
    per = []
    for (p, g), sub in pairs.groupby(["player", "gender"]):
        if len(sub) < 15:      # a correlation over a dozen contexts is not a number
            continue
        per.append((p, g, sub.agg0.corr(sub.agg1), sub.fin0.corr(sub.fin1)))
    per = pd.DataFrame(per, columns=["player", "gender", "r_agg", "r_fin"]).dropna()

    r_agg, r_fin = pairs.agg0.corr(pairs.agg1), pairs.fin0.corr(pairs.fin1)
    md.append("## Why the numerator counts induced forced errors")
    md.append("")
    md.append("Through 2026-08-05 this experiment counted only shots that ended the "
              "point on the player's own racquet — a winner or their own unforced "
              "error. Call that the **finishing shot frequency**. The wider and "
              "standard reading also credits a shot that forced the reply into an "
              "error, which is the **aggressive shot frequency** shipped above. The "
              "worry about widening it is that the forced/unforced call is the most "
              "charter-subjective field in the notation, so the extra events might be "
              "mostly noise. They are not.")
    md.append("")
    md.append("Each player's matches are split at random into halves and every "
              f"well-supported context (≥{MIN_HALF} strokes in *both* halves) is "
              "measured twice. The correlation between the two measurements is the "
              "share of the apparent between-context spread that replicates. Because "
              "the split is by match, charters disagreeing with each other lands "
              "inside the noise term this is testing.")
    md.append("")
    md.append("| | finishing (w+ue) | aggressive (+induced FE) |")
    md.append("|---|--:|--:|")
    md.append(f"| split-half r, all {len(pairs):,} contexts | {r_fin:+.3f} | "
              f"**{r_agg:+.3f}** |")
    md.append(f"| per-player median r ({len(per)} players) | {per.r_fin.median():+.3f} | "
              f"**{per.r_agg.median():+.3f}** |")
    md.append(f"| players it is more reliable for | {(per.r_fin > per.r_agg).mean():.0%} | "
              f"**{(per.r_agg > per.r_fin).mean():.0%}** |")
    md.append(f"| mean base frequency | {defs.base_fin.mean():.1%} | "
              f"{defs.base_agg.mean():.1%} |")
    md.append(f"| mean conversion | {defs.conv_fin.mean():.1%} | "
              f"{defs.conv_agg.mean():.1%} |")
    md.append("")
    md.append("The wider numerator wins, and it wins against a handicap: a base rate "
              f"moving from {defs.base_fin.mean():.1%} to {defs.base_agg.mean():.1%} "
              "raises the binomial noise floor by about a fifth, so a numerator made "
              "of noise would have *lost* this test. The extra events carry structure.")
    md.append("")
    md.append("Two things follow. First, the player ranking barely moves — the two "
              f"frequencies correlate {defs.base_fin.corr(defs.base_agg):+.3f} across "
              "players — so this is not a rewrite of who is aggressive. Second, the "
              "*composition* moves a lot, and not at random: induced forced errors "
              f"are {defs.fe_share.mean():.0%} of the numerator on average but range "
              f"from {defs.fe_share.min():.0%} to {defs.fe_share.max():.0%}. The "
              "narrow definition systematically under-credited players whose "
              "aggression works by pressure rather than by clean winners.")
    md.append("")
    md.append("| most under-credited by the old numerator | induced FE share | "
              "least |  induced FE share |")
    md.append("|---|--:|---|--:|")
    hi = defs.nlargest(5, "fe_share").reset_index()
    lo = defs.nsmallest(5, "fe_share").reset_index()
    for i in range(5):
        h, m = hi.iloc[i], lo.iloc[i]
        md.append(f"| {h.player} ({h.gender}) | {h.fe_share:.0%} | {m.player} "
                  f"({m.gender}) | {m.fe_share:.0%} |")
    md.append("")
    both = flips[(flips.tag != "neutral") | (flips.fin_tag != "neutral")]
    n_agg = int((flips.tag != "neutral").sum())
    n_fin = int((flips.fin_tag != "neutral").sum())
    md.append(f"The cue lists move more than the leaderboard does. Of the "
              f"{len(both):,} contexts either definition flags, they agree on "
              f"{(both.tag == both.fin_tag).mean():.0%}; the old numerator flagged "
              f"{n_fin:,} and this one flags {n_agg:,}. Traps fall from "
              f"{int((flips.fin_tag == 'trap').sum()):,} to "
              f"{int((flips.tag == 'trap').sum()):,}, which is the substantive "
              "correction: a shot that forced an error used to count as neither a "
              "success nor an aggressive shot, so a cue that reliably produced them "
              "read as low-conversion and got labelled a trap it had not earned.")
    md.append("")
    md.append("![definitions](figures/shot_triggers_definitions.png)")
    md.append("")
    md.append("**What this test does not cover.** Split-half catches charters "
              "disagreeing with each other, not a bias they share. If the tour's "
              "charters collectively over-call *forced* for one kind of player, both "
              "definitions inherit it and this comparison would not show it.")
    md.append("")
    return per


def _role_of(anchor: str) -> str:
    return "serve" if anchor == "serve+1" else "return"


def opening_rows(openings: dict, gender: str, qualifying: set) -> list:
    """Tag opening contexts green/trap against the player's own baseline *for the
    same shot and side* (their deuce serve+1 norm, their ad return+1 norm, ...).

    Only non-neutral (trigger) rows survive, matching the pooled analysis: a
    context clears ``MIN_CTX`` strokes, lifts the frequency ``TRIGGER_LIFT``x
    over that baseline on ``MIN_ATT``+ aggressive shots, then splits green
    (conversion holds) vs trap (conversion falls). Side is a grouping key, so on the deuce
    side a ``serve wide`` context is a deuce-wide serve — the disambiguation the
    pooled tables can't make."""
    rows = []
    for (player, side, anchor), rec in openings.items():
        if player not in qualifying:
            continue
        bn, bw, be, bf = rec["base"]
        batt = bw + be + bf
        if bn < OPEN_MIN_BASE or batt == 0:
            continue
        base_att, base_conv = batt / bn, (bw + bf) / batt
        for ctx, (n, w, e, f) in rec["ctx"].items():
            att = w + e + f
            if n < MIN_CTX or att < MIN_ATT:
                continue
            att_lift = (att / n) / base_att if base_att else 0.0
            if att_lift < TRIGGER_LIFT:
                continue
            conv = (w + f) / att
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
                md.append(f"- ✅ `{r['context']}` → {r['anchor']} aggressive {r['att_rate']:.0%} "
                          f"({r['att_lift']:.1f}×), converts {r['conversion']:.0%} "
                          f"({r['conv_delta']:+.0%} vs norm) (n={r['n']})")
            for r in traps:
                md.append(f"- ⚠️ `{r['context']}` → {r['anchor']} aggressive {r['att_rate']:.0%} "
                          f"({r['att_lift']:.1f}×) but converts only {r['conversion']:.0%} "
                          f"({r['conv_delta']:+.0%} vs norm) (n={r['n']})")
            md.append("")


def main() -> None:
    con = connect(read_only=True)
    md = ["# Shot-making triggers — aggressive shot frequency, conversion, traps, immunity",
          ""]
    md.append("*Generated by `experiments/shot_triggers/run.py`. An **aggressive shot** = "
              "the player's stroke ended the point on their own racquet (winner, own "
              "unforced error) or forced the reply into an error; **aggressive shot "
              "frequency** = how often a rally stroke is one; **conversion** = the share "
              "that paid, meaning a winner or an induced forced error. Per player, contexts "
              "(two prior shots) are tagged **green light** (frequency up, conversion "
              "holds) or **trap** (frequency up, conversion below their norm). σ measures "
              "how context-driven the decision is (0 = context-blind), with binomial "
              "sampling noise subtracted. The numerator is justified against the narrower "
              "finishing-shot reading in its own section below.*")
    md.append("")
    csv_rows, player_rows = [], []
    corr_all, phi_rows = [], []
    open_rows, open_by_gender = [], {}
    def_rows, pair_rows, flip_rows = [], [], []
    hands = hand_map(con)
    for g in ("M", "W"):
        acc, openings = collect(con, g, hands)
        tables = {}
        for player, a in acc.items():
            if a["n"] < MIN_SHOTS or (a["w"] + a["e"] + a["f"]) == 0:
                continue
            df = tag_contexts(context_table(a), a)
            if not len(df):
                continue
            tables[player] = df
            agg_n = a["w"] + a["e"] + a["f"]
            def_rows.append({
                "player": player, "gender": g,
                "base_agg": df.attrs["base_att"], "base_fin": df.attrs["base_fin"],
                "conv_agg": df.attrs["base_conv"], "conv_fin": df.attrs["base_fin_conv"],
                "fe_share": a["f"] / agg_n,
            })
            for pair in split_half_pairs(a):
                pair_rows.append({"player": player, "gender": g, **pair})
            flip_rows += df[["tag", "fin_tag"]].to_dict("records")
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
                "fin_rate": round(df.attrs["base_fin"], 3),
                "fin_conversion": round(df.attrs["base_fin_conv"], 3),
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
              "with execution; frequency + conversion separates them.")
    md.append("")

    # -- which numerator? -----------------------------------------------------
    defs = pd.DataFrame(def_rows)
    pairs = pd.DataFrame(pair_rows)
    flips = pd.DataFrame(flip_rows)
    per_rel = definition_block(md, defs, pairs, flips)

    md.append("## Pattern-immunity leaderboard (σ)")
    md.append("")
    md.append("σ = the true between-context spread of a player's aggressive shot "
              "frequency, in probability points, after subtracting binomial sampling "
              "noise (so charting volume doesn't distort the comparison). 0 would mean "
              "the decision ignores the lead-up entirely.")
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
              "court. Here the opening aggressive shots — the return, the serve+1, and "
              "the return+1 — are split by side and scored against the player's own norm "
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
    a2.set_xlabel("between-context spread of aggressive shot frequency σ\n"
                  "(prob. points, noise-corrected)")
    a2.set_title("How cue-driven is the decision?")
    a2.legend(fontsize=8)
    fig.suptitle("Shot-making triggers: one decision, two outcomes")
    fig.tight_layout()
    figp = PROJECT_ROOT / "reports" / "figures" / "shot_triggers.png"
    figp.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figp, dpi=110)
    plt.close(fig)

    # -- definitions figure ----------------------------------------------------
    # Left: the paired reliability test, one dot per player, against the identity
    # line — the claim is "the mass sits above the line", which is what a reader
    # should be able to check by eye rather than take on a summary statistic.
    # Right: the spread of the induced-FE share, which is the "and it isn't a wash"
    # half of the argument. Two panels, one series each, so neither needs a legend.
    fig2, (b1, b2) = plt.subplots(1, 2, figsize=(11, 4.4))
    lim = [min(per_rel.r_fin.min(), per_rel.r_agg.min()) - 0.03,
           max(per_rel.r_fin.max(), per_rel.r_agg.max()) + 0.03]
    b1.plot(lim, lim, color="#9aa0a6", ls="--", lw=1, zorder=1)
    b1.scatter(per_rel.r_fin, per_rel.r_agg, s=22, color="#1a7f4b", alpha=0.55,
               linewidths=0, zorder=2)
    b1.set_xlim(lim)
    b1.set_ylim(lim)
    b1.set_aspect("equal")
    b1.set_xlabel("split-half r — finishing shots\n(winner + own unforced error)")
    b1.set_ylabel("split-half r — aggressive shots\n(+ induced forced errors)")
    b1.set_title("Reliability of the two numerators, per player")
    b1.annotate(f"above the line: {(per_rel.r_agg > per_rel.r_fin).mean():.0%} of players",
                xy=(0.04, 0.93), xycoords="axes fraction", fontsize=9, color="#1a7f4b")
    b2.hist(defs.fe_share * 100, bins=25, color="#b0512e", alpha=0.8)
    b2.axvline(defs.fe_share.mean() * 100, color="black", ls="--", lw=1,
               label=f"mean {defs.fe_share.mean():.0%}")
    b2.set_xlabel("induced forced errors, % of a player's aggressive shots")
    b2.set_ylabel("players")
    b2.set_title("What the old numerator was discarding")
    b2.legend(fontsize=8)
    for ax in (b1, b2):
        ax.grid(alpha=0.18, lw=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    fig2.suptitle("Which numerator? The wider one replicates better")
    fig2.tight_layout()
    fig2p = PROJECT_ROOT / "reports" / "figures" / "shot_triggers_definitions.png"
    fig2.savefig(fig2p, dpi=110)
    plt.close(fig2)

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
    print(f"wrote reports/shot_triggers.md + .csv ({len(csv_rows)} trigger rows) + figures")
    print(f"definitions: split-half r  aggressive {pairs.agg0.corr(pairs.agg1):+.3f}  vs  "
          f"finishing {pairs.fin0.corr(pairs.fin1):+.3f}  "
          f"({(per_rel.r_agg > per_rel.r_fin).mean():.0%} of players favour aggressive)")
    print(f"wrote reports/shot_triggers_openings.csv ({len(open_rows)} side-split rows)")


if __name__ == "__main__":
    main()
