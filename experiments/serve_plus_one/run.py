"""Serve+1: what the server does with the ball the return gives back, at the
finest resolution each player's charting can fund.

Run:  python experiments/serve_plus_one/run.py

`court_response`'s "off the return" family already profiles this shot — the
server's third ball — keyed by the return's character, landing zone and depth.
It pools the two service courts, and that pooling is not free. A wide serve opens
the forehand in the deuce court and the backhand in the ad court, so the same
return description arrives from a different serve, at a different angle, with the
server recovering from a different corner. Nadal's pooled reading is "mid-depth
drive return into the middle -> crosscourt forehand, 1.7x". Split, it is a
crosscourt forehand off the deuce-court T serve and a forehand *down the line*
off the ad-court wide serve. The pooled number is the average of two different
shots, and it names neither.

The obvious fix — add serve side and serve direction to the state — costs
coverage: the state space goes six times finer and the tail of the tour can no
longer fund it. So the resolution is chosen per player rather than for the tour,
over three tiers:

    full    side x serve direction x return kind x zone x depth
    side    side x return kind x zone x depth
    pooled  return kind x zone x depth            (court_response's state)

A player is assigned the finest tier their *coverage* supports, counted before
any lift is looked at: MIN_TIER_STATES states of MIN_STATE observations each.
Choosing the tier by which one surfaced the most patterns would be choosing the
resolution that flattered the player, and no replication gate fully undoes that.

Everything else is court_response's method, imported from it rather than copied:
hand-relative zones, the crosscourt/down-the-line reference lane, shrunk lift
against the field in the same state, the payoff, and the both-halves replication
gate. This experiment does not modify or re-run that one.

Writes reports/serve_plus_one.md, reports/serve_plus_one_players.csv, and
reports/figures/serve_plus_one_tiers.png.
"""

import csv
import importlib.util
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import parse_point, stroke_kind  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402
from match_charting_project.stats import bh, binom_tail  # noqa: E402

REPORTS = PROJECT_ROOT / "reports"
FIG = REPORTS / "figures"
GLABEL = {"M": "Men", "W": "Women"}

# Surfacing gates. The first five are court_response's, unchanged, so a tier-"pooled"
# row here means what the same row means there and the two are readable side by side.
MIN_STATE = 80        # times a player must face a state to be profiled on it
MIN_CELL = 10         # raw count behind any surfaced response
MIN_FIELD = 500       # field observations of the state (minus the player's own)
K_SHRINK = 30         # pseudo-count pull toward the field distribution
K_CONV = 20           # pseudo-count pull of a pattern's win rate toward the field's
LIFT_MIN = 1.4        # shrunk lift needed to surface
HALF_LIFT_MIN = 1.15  # raw lift required in *both* halves of their matches
HALF_MIN = 4          # raw count required in both halves
TOP_PER_PLAYER = 2    # patterns surfaced per player (the panel shows two)
Q_FDR = 0.10          # Benjamini-Hochberg false-discovery rate, within player

# The lift gate above is a threshold on a point estimate, and a full-tier player is put
# through it on the order of fifty to a hundred times — once per state x response cell
# their charting funds. Without a correction that is a search, not a test: of the 770
# rows this used to ship, 170 sat above an uncorrected p=0.001 against the field share
# they were measured on, 57 above p=0.01 and 9 above p=0.05.
#
# So every cell that has a field baseline gets an exact binomial tail against that
# baseline, and the tails are Benjamini-Hochberg adjusted across that player's own
# candidate cells. Within player is the right family: the panel's claim is "this player
# does this unusually often", so what has to be controlled is how many tendencies were
# tried on them. This is the same correction deep_patterns applies, and it is applied
# here for the same reason — the two sections sit one above the other in the panel and a
# reader has no way to tell that one was screened and the other was not.

# Tier assignment. Deliberately a coverage test, not a results test: a player earns
# the finer state by having faced enough distinct situations in it, whatever those
# situations turned out to say.
MIN_TIER_STATES = 4

SERVE_DIRS = {"4", "5", "6"}
DIRS = {"1", "2", "3"}
DEPTHS = {"7", "8", "9"}
SIDE_WORD = {"deuce": "deuce court", "ad": "ad court"}
SDIR_WORD = {"4": "wide serve", "5": "body serve", "6": "T serve"}
MARQUEE = {
    "M": ["Roger Federer", "Novak Djokovic", "Rafael Nadal", "Pete Sampras",
          "Daniil Medvedev", "Stefan Edberg"],
    "W": ["Serena Williams", "Iga Swiatek", "Steffi Graf", "Angelique Kerber",
          "Caroline Wozniacki", "Bianca Andreescu"],
}


def _court_response():
    """Load the sibling experiment as a module without running it (it guards main()).

    Its geometry is the vocabulary this experiment extends — hand-relative zones,
    the reference lane that decides crosscourt from down-the-line, the plain-language
    words, and the physical codes the site's court renderer draws from. A second copy
    here would drift the moment either side was corrected.
    """
    path = Path(__file__).resolve().parents[1] / "court_response" / "run.py"
    spec = importlib.util.spec_from_file_location("court_response_run", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CR = _court_response()
ZONE_REL, WING_LANE, MIRROR = CR.ZONE_REL, CR.WING_LANE, CR.MIRROR
INC_WORD, RESP_WORD, ZONE_WORD, DEPTH_WORD = (
    CR.INC_WORD, CR.RESP_WORD, CR.ZONE_WORD, CR.DEPTH_WORD)


class State(NamedTuple):
    """One serve+1 situation. ``side`` and ``sdir`` are None at the coarser tiers,
    which is also what distinguishes a tier — the same observation is counted into
    all three, and the None-ness of the tuple says which one a row belongs to."""

    side: "str | None"      # deuce / ad
    sdir: "str | None"      # serve direction 4/5/6
    kind: str               # the return's stroke kind
    zone: str               # where it landed, relative to the server's hands
    depth: str              # the return's charted depth


def tier_of(st: State) -> str:
    return "full" if st.sdir else ("side" if st.side else "pooled")


TIERS = ("full", "side", "pooled")
TIER_WORD = {"full": "side + serve direction", "side": "side only",
             "pooled": "sides pooled"}


def states_for(side, sdir, kind, zone, depth) -> list:
    """The same observation at all three resolutions, finest first.

    The full tier is skipped when the serve's direction was not charted. That is a
    real cost the coarser tiers do not pay, and the report counts it rather than
    letting those points quietly widen the gap between tiers.
    """
    out = []
    if sdir in SERVE_DIRS:
        out.append(State(side, sdir, kind, zone, depth))
    out.append(State(side, None, kind, zone, depth))
    out.append(State(None, None, kind, zone, depth))
    return out


def collect(con, gender: str, hands: dict) -> dict:
    """One pass over the gender's points.

    ``per[player]`` is a (half0, half1) pair of {state: Counter(response)}, and
    ``perw`` the same counting only points the server went on to win. ``field`` and
    ``fieldw`` are the tour-wide equivalents, which each player is scored against
    with their own shots subtracted. Matches, not points, are the split unit, so a
    charter's judgment of depth lands wholly on one side of the replication test.
    """
    per = defaultdict(lambda: (defaultdict(Counter), defaultdict(Counter)))
    perw = defaultdict(lambda: (defaultdict(Counter), defaultdict(Counter)))
    field, fieldw = defaultdict(Counter), defaultdict(Counter)
    funnel = Counter()

    cur = con.execute(
        "SELECT m.match_id, m.player1, m.player2, p.svr, p.pts, p.first_serve, "
        "       p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?", [gender])
    while True:
        batch = cur.fetchmany(100_000)
        if not batch:
            break
        for mid, p1, p2, svr, pts, fs, ss, win in batch:
            funnel["points"] += 1
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            funnel["parsed"] += 1
            if len(pt.shots) < 3:
                continue
            funnel["reached3"] += 1
            serve, ret, plus1 = pt.shots[0], pt.shots[1], pt.shots[2]
            if plus1.idx != 3 or plus1.side not in ("FH", "BH"):
                continue
            d_in, d_out = ret.direction, plus1.direction
            if d_in not in DIRS or d_out not in DIRS or ret.depth not in DEPTHS:
                continue
            side = serve_side(pts)
            if side not in ("deuce", "ad"):
                funnel["no_side"] += 1
                continue
            name = {1: p1, 2: p2}[plus1.hitter]
            hand = hands.get(name)
            if hand is None:
                funnel["no_hand"] += 1
                continue
            funnel["obs"] += 1
            if serve.direction not in SERVE_DIRS:
                funnel["no_serve_dir"] += 1

            kind, zone = stroke_kind(ret.letter, False), ZONE_REL[hand][d_in]
            ref = d_in if d_in != "2" else WING_LANE[hand][plus1.side]
            line = "cc" if d_out == ref else ("dtl" if d_out == MIRROR[ref] else "mid")
            resp = (plus1.side, stroke_kind(plus1.letter, False), line)
            # The server hit shot 3, so "won" is whether the point ended with them —
            # the payoff of the decision, terminal shot or not.
            won = int(plus1.hitter == (pt.server if pt.server_won else pt.returner))
            half = zlib.crc32(str(mid).encode()) & 1
            for st in states_for(side, serve.direction, kind, zone, ret.depth):
                per[name][half][st][resp] += 1
                field[st][resp] += 1
                if won:
                    perw[name][half][st][resp] += 1
                    fieldw[st][resp] += 1
    return {"per": per, "perw": perw, "field": field, "fieldw": fieldw,
            "funnel": funnel}


def tier_states(res, name, tier) -> dict:
    """{state: total} for one player at one tier, states below MIN_STATE dropped."""
    h0, h1 = res["per"][name]
    out = {}
    for st in set(h0) | set(h1):
        if tier_of(st) != tier:
            continue
        n = h0[st].total() + h1[st].total()
        if n >= MIN_STATE:
            out[st] = n
    return out


def assign_tier(res, name) -> str:
    """The finest tier this player's coverage funds — decided before any lift."""
    for tier in TIERS:
        if len(tier_states(res, name, tier)) >= MIN_TIER_STATES:
            return tier
    return "pooled"


def profile(res, name, tier) -> list:
    """A player's surfaced patterns at their assigned tier, best evidence first.

    Every gate is court_response's, applied against the field in the *same* state,
    so a full-tier pattern is compared to the tour's answers to that same serve,
    into that same court, off that same return.

    ``p_field`` and ``sconv`` ride along for the same reasons they do there: the card
    needs to show what share of the field plays a response before "3.4x" means anything
    (3.4x off a 27% base and 3.4x off a 0.4% base are different claims), and the
    player's own win rate on this serve-and-return, across every third ball they hit
    from it, is the only payoff comparison that is not mostly a statement about how
    good they are. Unlike court_response this field is *not* era-standardized — the
    serve+1 state already carries the service court and the serve's direction, which
    thins each cell enough that a per-era baseline would price very few of them.
    """
    h0, h1 = res["per"][name]
    h0w, h1w = res["perw"][name]
    out, pending = [], []
    for st, n in tier_states(res, name, tier).items():
        c0, c1 = h0[st], h1[st]
        mine = c0 + c1
        base = res["field"][st] - mine
        bn = base.total()
        if bn < MIN_FIELD:
            continue
        mine_w = h0w[st] + h1w[st]
        p_state = (res["fieldw"][st] - mine_w).total() / bn
        sconv = (mine_w.total() + K_CONV * p_state) / (n + K_CONV) if n else p_state
        for resp, c in mine.items():
            bf = base.get(resp, 0)
            if c < MIN_CELL or bf < 20:
                continue
            p_field = bf / bn
            # Every cell with a baseline is a test that was performed, whether or not it
            # goes on to clear the lift gate — so the tail is taken here, before any of
            # the surfacing gates, and the whole set forms the correction family.
            pval = binom_tail(c, n, p_field)
            lift = ((c + K_SHRINK * p_field) / (n + K_SHRINK)) / p_field
            surfaces = lift >= LIFT_MIN and min(c0[resp], c1[resp]) >= HALF_MIN
            n0, n1 = c0.total(), c1.total()
            if surfaces and n0 and n1:
                l0, l1 = (c0[resp] / n0) / p_field, (c1[resp] / n1) / p_field
                surfaces = min(l0, l1) >= HALF_LIFT_MIN
            else:
                l0 = l1 = 0.0
                surfaces = False
            if not surfaces:
                pending.append((pval, None))
                continue
            wins = h0w[st][resp] + h1w[st][resp]
            fconv = (res["fieldw"][st].get(resp, 0) - wins) / bf
            conv = (wins + K_CONV * fconv) / (c + K_CONV)
            pending.append((pval, (c * np.log2(lift), lift, st, resp, n, c, l0, l1,
                                   conv, fconv, p_field, sconv)))
    # Adjust across the player's whole candidate set, then keep the survivors that also
    # cleared the surfacing gates.
    for (pval, row), q in zip(pending, bh([p for p, _ in pending])):
        if row is not None and q <= Q_FDR:
            out.append(row)
    out.sort(key=lambda r: -r[0])
    return out[:TOP_PER_PLAYER]


# --- naming --------------------------------------------------------------------------

def state_name(st: State) -> str:
    ball = f"{DEPTH_WORD[st.depth]} {INC_WORD[st.kind]} return into {ZONE_WORD[st.zone]}"
    if st.sdir:
        return f"{SIDE_WORD[st.side]}, {SDIR_WORD[st.sdir]} · {ball}"
    if st.side:
        return f"{SIDE_WORD[st.side]} · {ball}"
    return ball


def resp_name(st: State, resp) -> str:
    wing, kind, line = resp
    word = RESP_WORD[kind]
    if line == "mid":
        return f"{wing} {word} through the middle"
    run_around = (st.zone in ("fh", "bh") and st.zone != wing.lower()
                  and kind in ("drive", "slice"))
    if run_around:
        return f"{'inside-out' if line == 'cc' else 'inside-in'} {wing} {word}"
    return f"crosscourt {wing} {word}" if line == "cc" else f"{wing} {word} down the line"


def physical_codes(st: State, resp, hand):
    """Zone codes for the site's court renderer: where the return landed and where
    the +1 went, as thirds of the court in the fixed right-hander convention."""
    zone, (wing, _kind, line) = st.zone, resp
    inc = "2" if zone == "mid" else {"R": {"fh": "1", "bh": "3"},
                                     "L": {"fh": "3", "bh": "1"}}[hand][zone]
    ref = inc if inc != "2" else WING_LANE[hand][wing]
    out = ref if line == "cc" else (MIRROR[ref] if line == "dtl" else "2")
    return inc, out


# --- what the pooling costs ----------------------------------------------------------

def side_flips(res, name) -> list:
    """Situations where the two courts disagree about the player's *first choice*.

    For every pooled state both courts fund on their own, the most-played response
    on the deuce side against the most-played on the ad side. A disagreement is the
    exact thing the pooled row cannot report: it names one of the two and buries
    the other inside an average.
    """
    h0, h1 = res["per"][name]
    by_pooled = defaultdict(dict)
    for st in set(h0) | set(h1):
        if tier_of(st) != "side":
            continue
        c = h0[st] + h1[st]
        if c.total() >= MIN_STATE:
            by_pooled[(st.kind, st.zone, st.depth)][st.side] = c
    out = []
    for key, sides in by_pooled.items():
        if len(sides) < 2:
            continue
        (rd, nd), (ra, na) = ((sides[s].most_common(1)[0][0], sides[s].total())
                              for s in ("deuce", "ad"))
        if rd != ra:
            st = State(None, None, *key)
            out.append((st, rd, nd, ra, na))
    return out


# --- figure --------------------------------------------------------------------------

def fig_tiers(results, surfaced, path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))

    # Players who surfaced a pattern, not players assigned a tier. Every entity with a
    # single charted match is assigned the pooled tier and clears no gate after it, so
    # an assignment chart is a chart of how many names are in the database.
    ax = axes[0]
    width, xs = 0.38, np.arange(len(TIERS))
    for i, g in enumerate(("M", "W")):
        ax.bar(xs + (i - 0.5) * width, [surfaced[g][t] for t in TIERS], width,
               label=GLABEL[g], color=("#2c6fbb", "#b0512e")[i])
    ax.set_xticks(xs)
    ax.set_xticklabels([TIER_WORD[t] for t in TIERS], fontsize=8)
    ax.set_ylabel("players with a surfaced pattern")
    ax.set_title("Resolution the profiled players are read at")
    ax.legend(fontsize=8)

    ax = axes[1]
    for g, color in (("M", "#2c6fbb"), ("W", "#b0512e")):
        xs_, ys_ = results[g]["stab"]
        if not len(xs_):
            continue
        r = np.corrcoef(xs_, ys_)[0, 1]
        ax.scatter(xs_, ys_, s=4, alpha=0.15, color=color, label=f"{GLABEL[g]} r={r:.2f}")
    lim = 3.0
    ax.plot([-lim, lim], [-lim, lim], color="gray", lw=0.8, ls=":")
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.set_xlabel("log2 lift — half 1 of a player's matches")
    ax.set_ylabel("log2 lift — half 2")
    ax.set_title("Full-tier cells, split-half")
    ax.legend(fontsize=8)

    fig.suptitle("Serve+1: how fine a state each player can fund, and does it hold up")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=110)
    plt.close(fig)


def stability_cells(res, min_half=40, min_total=10, k=15):
    """Per-half shrunk log-lifts for well-populated full-tier cells: the honesty
    check on the finest state, where the counts are thinnest and the claim boldest."""
    xs, ys = [], []
    for name, (h0, h1) in res["per"].items():
        for st in set(h0) | set(h1):
            if tier_of(st) != "full":
                continue
            c0, c1 = h0[st], h1[st]
            n0, n1 = c0.total(), c1.total()
            if min(n0, n1) < min_half:
                continue
            base = res["field"][st] - (c0 + c1)
            bn = base.total()
            if bn < MIN_FIELD:
                continue
            for resp in set(c0) | set(c1):
                if c0[resp] + c1[resp] < min_total:
                    continue
                bf = base.get(resp, 0)
                if bf < 20:
                    continue
                p = bf / bn
                xs.append(np.log2(((c0[resp] + k * p) / (n0 + k)) / p))
                ys.append(np.log2(((c1[resp] + k * p) / (n1 + k)) / p))
    return np.array(xs), np.array(ys)


# --- report --------------------------------------------------------------------------

def player_block(md, name, rows_by_player, tiers, flips):
    rows = rows_by_player.get(name)
    if not rows:
        return
    md.append(f"**{name}** — tier: {TIER_WORD[tiers[name]]}\n")
    for r in rows:
        md.append(f"- {r['state']} → **{r['response']}** ({r['lift']}x vs "
                  f"{r['field_share']:.0%} of the field, "
                  f"n={r['count']}/{r['n_state']}, halves {r['lift_h1']}/{r['lift_h2']}, "
                  f"wins {r['win_rate']:.0%} vs {r['state_win_rate']:.0%} on this ball "
                  f"overall, tour {r['tour_win_rate']:.0%})")
    for st, rd, nd, ra, na in flips.get(name, [])[:2]:
        md.append(f"  - *courts disagree*: {state_name(st)} → "
                  f"{resp_name(st, rd)} on the deuce side (n={nd}), "
                  f"{resp_name(st, ra)} on the ad side (n={na})")
    md.append("")


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    hands = CR.hand_map(con)
    results = {g: collect(con, g, hands) for g in ("M", "W")}
    con.close()

    rows, tiers, counts, flips_by_g = [], {}, {}, {}
    for g in ("M", "W"):
        res = results[g]
        res["stab"] = stability_cells(res)
        counts[g] = Counter()
        flips_by_g[g] = {}
        for name in res["per"]:
            tier = assign_tier(res, name)
            counts[g][tier] += 1
            tiers[name] = tier
            flips_by_g[g][name] = side_flips(res, name)
            hand = hands[name]
            for (ev, lift, st, resp, n, c, l0, l1,
                 conv, fconv, pf, sconv) in profile(res, name, tier):
                inc, out = physical_codes(st, resp, hand)
                rows.append(dict(
                    player=name, gender=g, hand=hand, family="ret", tier=tier,
                    state=state_name(st), response=resp_name(st, resp),
                    serve_side=st.side or "", serve_dir=st.sdir or "",
                    state_kind=st.kind, state_zone=st.zone,
                    state_depth=DEPTH_WORD[st.depth],
                    resp_wing=resp[0], resp_kind=resp[1], resp_line=resp[2],
                    inc_code=inc, resp_code=out,
                    n_state=n, count=c, lift=round(lift, 2), evidence=round(ev, 1),
                    lift_h1=round(l0, 2), lift_h2=round(l1, 2),
                    field_share=round(pf, 4), state_win_rate=round(sconv, 3),
                    win_rate=round(conv, 3), tour_win_rate=round(fconv, 3)))

    surfaced = {g: Counter() for g in ("M", "W")}
    for g in ("M", "W"):
        for tier in TIERS:
            surfaced[g][tier] = len({r["player"] for r in rows
                                     if r["gender"] == g and r["tier"] == tier})
    fig_tiers(results, surfaced, FIG / "serve_plus_one_tiers.png")

    with open(REPORTS / "serve_plus_one_players.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    by_player = defaultdict(list)
    for r in rows:
        by_player[r["player"]].append(r)

    md = ["# Serve+1: the server's third ball, at fundable resolution", ""]
    md.append(f"*Generated by `experiments/serve_plus_one/run.py`. The shot is the "
              f"server's third ball. The state is the serve that opened the point — "
              f"which court, which direction — and the return that came back: its "
              f"stroke kind, the zone it landed in named relative to the server's own "
              f"hands, and its charted depth. The response is the server's decision: "
              f"wing, shot type, and line. Lift compares the player's response rate in "
              f"that state to the rest of the field in the same state (their own shots "
              f"excluded), shrunk toward 1 by {K_SHRINK} pseudo-counts, and each pattern "
              f"carries its payoff — the player's point-win rate after playing it, next "
              f"to the field's playing the same response to the same ball. Gates: "
              f"n≥{MIN_STATE} in the state, count≥{MIN_CELL}, field n≥{MIN_FIELD}, "
              f"shrunk lift≥{LIFT_MIN}, and raw lift≥{HALF_LIFT_MIN} in both halves of "
              f"the player's charted matches. Each player is profiled at the finest of "
              f"three state tiers their coverage funds — {MIN_TIER_STATES} states of "
              f"{MIN_STATE}+ observations — decided before any lift is computed.*")
    md.append("")

    md.append("## Tier assignment")
    md.append("")
    md.append("Assigned, then — in brackets — how many of those went on to surface a "
              "pattern. Every entity with a single charted match is assigned the pooled "
              "tier and clears no gate after it, which is what the third column mostly "
              "counts.")
    md.append("")
    md.append("| tour | " + " | ".join(TIER_WORD[t] for t in TIERS) + " |")
    md.append("| --- | " + " | ".join("---" for _ in TIERS) + " |")
    for g in ("M", "W"):
        md.append(f"| {GLABEL[g]} | " + " | ".join(
            f"{counts[g][t]:,} ({surfaced[g][t]:,})" for t in TIERS) + " |")
    md.append("")

    for g in ("M", "W"):
        f = results[g]["funnel"]
        md.append(f"- **{GLABEL[g]}**: {f['points']:,} points → {f['parsed']:,} parsed → "
                  f"{f['reached3']:,} reached a third shot → {f['obs']:,} usable serve+1 "
                  f"observations (both directions and the return's depth charted, and a "
                  f"known hand for the server).")
    md.append("")
    md.append("The finest tier needs the serve's direction, which the coarser two do not, "
              "and that turned out to cost almost nothing: "
              + ", ".join(f"{GLABEL[g]} {results[g]['funnel']['no_serve_dir']:,}"
                          for g in ("M", "W"))
              + " observations carry no charted serve direction, well under a tenth of a "
                "percent on either tour. Requiring the return's *depth* has already "
                "selected points from charters working at full detail, and those charters "
                "record the serve.")
    md.append("")

    n_full = sum(1 for r in rows if r["tier"] == "full")
    n_side = sum(1 for r in rows if r["tier"] == "side")
    md.append(f"{len(rows):,} patterns across {len(by_player):,} players: "
              f"{n_full:,} at full resolution, {n_side:,} side-only, "
              f"{len(rows) - n_full - n_side:,} pooled.")
    md.append("")

    md.append("## What the pooling was costing")
    md.append("")
    md.append("A *court disagreement* is a situation both service courts fund on their "
              "own, where the player's most-played answer differs between them. The "
              "pooled state cannot report one of these: it names whichever response won "
              "the average and buries the other.")
    md.append("")
    for g in ("M", "W"):
        fl = flips_by_g[g]
        tot = sum(len(v) for v in fl.values())
        who = sum(1 for v in fl.values() if v)
        md.append(f"- **{GLABEL[g]}**: {tot:,} disagreements across {who:,} players.")
    md.append("")

    for g in ("M", "W"):
        md.append(f"### {GLABEL[g]}\n")
        for name in MARQUEE[g]:
            player_block(md, name, by_player, tiers, flips_by_g[g])

    md.append("![tiers](figures/serve_plus_one_tiers.png)")
    md.append("")
    for g in ("M", "W"):
        xs, ys = results[g]["stab"]
        if len(xs):
            md.append(f"- {GLABEL[g]}: full-tier split-half r = "
                      f"{np.corrcoef(xs, ys)[0, 1]:.2f} over {len(xs):,} cells.")
    md.append("")

    (REPORTS / "serve_plus_one.md").write_text("\n".join(md))
    print(f"wrote reports/serve_plus_one.md and serve_plus_one_players.csv "
          f"({len(rows)} patterns, {len(by_player)} players)")


if __name__ == "__main__":
    main()
