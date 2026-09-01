"""Court-state response profiles: what a player does with a given incoming ball.

Run:  python experiments/court_response/run.py

The site's signature-pattern panel conditions on the opponent's full previous
token (wing + type + zone). That framing surfaces generic rally pairs, charting
artifacts (uncharted-direction tokens), and handedness masquerading as style —
a lefty answering his forehand corner with a forehand posts a huge lift against
a right-handed field. This experiment reframes the question the way a player
experiences it: the state is the incoming ball only — the zone it lands in,
named relative to the receiver's own hands, plus the ball's character — and the
response is the player's decision: wing, shot type, and the line taken
(the diagonal, against it, or through the middle). Everything upstream of the
incoming ball is deliberately ignored.

Zone geometry: direction codes name fixed thirds ("1" = a right-hander's
forehand corner), and the two ends face each other, so a reply to the *same*
code travels the diagonal and a reply to the mirrored code goes against it. For
balls arriving through the middle, the hitter's wing fixes the reference lane.

Naming those two lines needs the zone as well, because the same line has
different names depending on the corner it started from. A ball met in a corner
goes crosscourt on the diagonal and down the line against it. A ball met in the
middle has no down the line available — there is no corner behind it to line up
with — so it goes crosscourt or inside-out. Run-arounds (a forehand played from
the backhand corner) get inside-out and inside-in.

Two state families come out of one pass. Rally states are (ball character,
zone), depth-agnostic, for every rally pair. Return states add the charted
return depth (short / mid / deep) and cover only the server's shot 3 — the one
spot where depth is charted often enough (~74% of returns) to condition on:
what does the server do with a short return versus a deep one?

Each pattern also carries its payoff: how often the point ends up won by the
player after they play that response, next to how often the field wins it
playing the same response to the same ball. Choice (lift) and execution
(payoff) stay separate claims — a pet shot can be overused, underused, or
simply better in their hands.

A pattern is surfaced only if it clears the gates below, including split-half
stability: it must show up in both halves of the player's charted matches.

Writes reports/court_response.md, reports/court_response_players.csv, and a
stability figure.
"""

import csv
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import parse_point, stroke_kind  # noqa: E402
from match_charting_project.stats import bh, binom_tail  # noqa: E402

REPORTS = PROJECT_ROOT / "reports"
FIG = REPORTS / "figures"
GLABEL = {"M": "Men", "W": "Women"}

# Surfacing gates (all documented in the report).
MIN_STATE = 80        # times a player must face a state to be profiled on it
MIN_CELL = 10         # raw count behind any surfaced response
MIN_FIELD = 500       # field observations of the state (minus the player's own)
MIN_FIELD_ERA = 200   # field observations of a state *within one era* to price it there
ERA_COV_MIN = 0.60    # share of a player's balls an era-matched field must cover to be used

# The field a player is measured against is weighted to their own era. Tennis moves
# enough inside the charted corpus that a pooled field is the wrong comparison for
# anyone who played before most of it was recorded: among women answering a drive into
# the backhand corner, the crosscourt backhand slice runs 23.6% pre-2000 against 5.7%
# in the 2000s and 5.8% from 2010, and pre-2000 is a small fraction of all observations.
# Measured against the pooled field, Graf's slice posts a 7.3x lift of which most is
# simply the decade she played in — the shot was ordinary among the people she faced.
#
# So each cell's field share is the average of the per-era field shares, weighted by how
# the player's own balls are distributed across eras (indirect standardization). The
# question becomes "unusual among the people they actually played", which is the only
# version of it a scouting number can mean.
ERAS = ((0, 2000, "pre-2000"), (2000, 2010, "2000s"), (2010, 9999, "2010+"))
K_SHRINK = 30         # pseudo-count pull toward the field distribution
K_CONV = 20           # pseudo-count pull of a pattern's win rate toward the field's
LIFT_MIN = 1.4        # shrunk lift needed in the discovery fold to be a candidate
VAL_LIFT_MIN = 1.15   # shrunk lift the validation fold must still show to confirm
FOLD_STATE = 40       # times a player must face a state *within a fold*
FOLD_CELL = 5         # raw count behind a response *within a fold*
Q_FDR = 0.10          # Benjamini-Hochberg false-discovery rate, within player and fold
TOP_PER_PLAYER = 3    # rally patterns surfaced per player
TOP_RETURN = 2        # return-depth patterns surfaced per player

MIRROR = {"1": "3", "2": "2", "3": "1"}
# Direction codes name fixed thirds by the right-hander convention; relative to
# the receiver's own hands, code 1 is a righty's forehand corner, a lefty's backhand.
ZONE_REL = {"R": {"1": "fh", "2": "mid", "3": "bh"},
            "L": {"1": "bh", "2": "mid", "3": "fh"}}
WING_LANE = {"R": {"FH": "1", "BH": "3"}, "L": {"FH": "3", "BH": "1"}}

INC_WORD = {"drive": "drive", "slice": "slice", "net": "net ball", "other": "drop/lob"}
RESP_WORD = {"drive": "drive", "slice": "slice", "net": "net shot", "other": "drop/lob"}
ZONE_WORD = {"fh": "the FH corner", "mid": "the middle", "bh": "the BH corner"}
DEPTH_WORD = {"7": "short", "8": "mid-depth", "9": "deep"}


def hand_map(con):
    """Modal hand per player; the raw columns carry stray spaces and a few dates."""
    rows = con.execute(
        "SELECT player1, player1_hand FROM matches "
        "UNION ALL SELECT player2, player2_hand FROM matches").fetchall()
    votes = defaultdict(Counter)
    for name, hand in rows:
        h = (hand or "").strip().upper()
        if h in ("R", "L"):
            votes[name][h] += 1
    return {n: v.most_common(1)[0][0] for n, v in votes.items()}


def observations(pt, names, hands, funnel):
    """Yield (name, hand, state, resp, won) for consecutive rally-shot pairs.

    The incoming ball starts at the return (shot 2), so serve returns are not
    responses here — serve patterns already have their own experiment. States
    are (family, kind, zone, depth): every pair lands in the depth-agnostic
    "rally" family, and the server's shot 3 also lands in the "ret" family when
    the return's depth was charted. ``won`` is whether the point ended up with
    the responder — the payoff of the decision, terminal or not.
    """
    winner = pt.server if pt.server_won else pt.returner
    for prev, cur in zip(pt.shots[1:], pt.shots[2:]):
        funnel["pairs"] += 1
        if cur.side not in ("FH", "BH"):
            continue
        d_in, d_out = prev.direction, cur.direction
        if d_in not in ("1", "2", "3") or d_out not in ("1", "2", "3"):
            continue
        name = names[cur.hitter]
        hand = hands.get(name)
        if hand is None:
            continue
        kind, zone = stroke_kind(prev.letter, False), ZONE_REL[hand][d_in]
        ref = d_in if d_in != "2" else WING_LANE[hand][cur.side]
        line = "cc" if d_out == ref else ("dtl" if d_out == MIRROR[ref] else "mid")
        resp = (cur.side, stroke_kind(cur.letter, False), line)
        won = int(cur.hitter == winner)
        funnel["obs"] += 1
        yield name, hand, ("rally", kind, zone, ""), resp, won
        if cur.idx == 3 and prev.depth in DEPTH_WORD:
            funnel["ret_obs"] += 1
            yield name, hand, ("ret", kind, zone, prev.depth), resp, won


def era_of(year) -> str:
    y = int(year or 0)
    for lo, hi, label in ERAS:
        if lo <= y < hi:
            return label
    return ERAS[-1][2]


def analyze(con, gender, hands):
    field = defaultdict(Counter)   # state -> Counter(resp)
    fieldw = defaultdict(Counter)  # state -> Counter(resp) of points won
    per = defaultdict(lambda: (defaultdict(Counter), defaultdict(Counter)))
    perw = defaultdict(lambda: (defaultdict(Counter), defaultdict(Counter)))
    # The same tallies cut by era, for the standardized baseline. Kept beside the pooled
    # ones rather than replacing them: the pooled counts still carry the support gates
    # and the split-half check, and they are the fallback wherever an era is too thin to
    # price a state on its own.
    field_e = defaultdict(Counter)     # (state, era) -> Counter(resp)
    fieldw_e = defaultdict(Counter)
    per_e = defaultdict(lambda: defaultdict(Counter))    # name -> (state, era) -> Counter
    perw_e = defaultdict(lambda: defaultdict(Counter))
    funnel = Counter()
    res = con.execute(
        "SELECT m.player1, m.player2, p.match_id, p.svr, p.first_serve, "
        "p.second_serve, p.pt_winner, m.year "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?", [gender])
    while batch := res.fetchmany(50_000):
        for p1, p2, mid, svr, fs, ss, win, year in batch:
            funnel["points"] += 1
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            funnel["parsed"] += 1
            half = zlib.crc32(str(mid).encode()) & 1
            era = era_of(year)
            names = {1: p1, 2: p2}
            for name, hand, state, resp, won in observations(pt, names, hands, funnel):
                field[state][resp] += 1
                fieldw[state][resp] += won
                per[name][half][state][resp] += 1
                perw[name][half][state][resp] += won
                field_e[(state, era)][resp] += 1
                fieldw_e[(state, era)][resp] += won
                per_e[name][(state, era)][resp] += 1
                perw_e[name][(state, era)][resp] += won
    return dict(field=field, fieldw=fieldw, per=per, perw=perw, funnel=funnel,
                field_e=field_e, fieldw_e=fieldw_e, per_e=per_e, perw_e=perw_e)


def era_baseline(res, name, state, resp):
    """The field's share and win rate for one cell, weighted to a player's era mix.

    Returns ``(share, win_rate, covered)``. ``covered`` is how many of the player's
    balls in this state fell in eras the field can price at all; a state whose eras are
    mostly too thin falls back to the pooled baseline in ``profile``. The player's own
    observations come out of the field in each era separately, exactly as they do from
    the pooled one — otherwise a player who dominates a thin era is compared to himself.

    The win rate carries its own weights: an era where the field never plays the
    response has no win rate to contribute, and letting it weigh in at zero would read
    as "the tour loses every one of these" rather than "the tour does not do this".
    """
    sh_num = sh_den = wr_num = wr_den = 0.0
    for _lo, _hi, era in ERAS:
        mine = res["per_e"][name].get((state, era))
        if not mine:
            continue
        n_e = mine.total()
        base = res["field_e"][(state, era)] - mine
        bn = base.total()
        if bn < MIN_FIELD_ERA:
            continue
        bf = base.get(resp, 0)
        sh_num += n_e * (bf / bn)
        sh_den += n_e
        if bf:
            mw = res["perw_e"][name].get((state, era), Counter()).get(resp, 0)
            wr_num += n_e * ((res["fieldw_e"][(state, era)].get(resp, 0) - mw) / bf)
            wr_den += n_e
    return (sh_num / sh_den if sh_den else None,
            wr_num / wr_den if wr_den else None, sh_den)


def shrunk_lift(c, n, p_field, k=K_SHRINK):
    return ((c + k * p_field) / (n + k)) / p_field


def profile(res, name, audit=None):
    """A player's surfaced patterns, each discovered in one fold and measured in the other.

    Returns ``(ev, lift, state, resp, n, c, disc_lift, folds, conv, fconv, p_field,
    sconv, q, n_cand)``.

    Two things keep this screen honest.

    **A multiplicity correction.** A player is screened on a median of 17 (state, response)
    candidates and up to 208 — 35,979 across the tour — so a fixed lift threshold with no
    test behind it would not account for how many tendencies had been tried on a player
    before one cleared. Each fold's candidates get an exact binomial
    tail against the field's share for that state, Benjamini-Hochberg adjusted across every
    cell that fold screened for that player. Within player is the right family: the panel's
    claim is "this player answers this ball unusually", so the multiplicity that matters is
    how many answers were tried on them. (The responses to one state are multinomial rather
    than independent binomials, so the per-cell tail is an approximation; BH across the
    family is what the honesty rests on, not the exactness of any one tail.)

    **Held-out figures.** The old screen required a raw lift in *both* halves and then
    printed the pooled lift — so both halves voted on selection and the number shown was
    measured on all of it, which is the winner's curse the panel had no defence against.
    Now each fold takes a turn discovering, and the lift, payoff and counts are read off
    the fold that had no part in it. A pattern confirmed from both directions shows the two
    halves pooled, which is the mean of two held-out measurements rather than a return to
    in-sample figures; one confirmed from a single direction shows that validation fold
    alone. ``disc_lift`` carries the mean discovery-fold lift beside it, so the shrinkage
    between finding a pattern and measuring it is visible per row.

    Still ranked by evidence = count x log2(lift), the cell's contribution to the player's
    divergence from the field — raw lift alone crowns rare quirks (a 5x lift on 60 of
    29,000 balls) over bread-and-butter tendencies. ``conv`` is the player's point-win rate
    playing that response (shrunk toward the field's by K_CONV pseudo-counts); ``fconv`` is
    the field's, same state and response, the player's own points excluded. ``p_field`` is
    the share the lift is taken against. ``sconv`` is the player's own point-win rate across
    every answer they give to this same ball.

    ``sconv`` exists because ``conv`` against ``fconv`` is mostly a strength comparison: the
    gap between the two correlates about +0.43 with a player's overall serve-plus-return
    rate, so the strongest thirty players beat the tour on nearly every pattern they have
    and the weakest thirty lose on nearly all of theirs, whatever the tactic is worth. Both
    sides of ``conv`` vs ``sconv`` are the same player on the same incoming ball, so what is
    left is the choice.

    **Not done here:** the opening and the rally are still pooled. A (player, state) cell
    counts the serve+1 ball together with the same-described ball at shot 11, and for 691 of
    4,218 well-supported cells (16.4%, against 0 of 5,040 on a coin-flip control) the
    response a player picks differs measurably between the two. The fix is a heterogeneity
    pass over the survivors below — split the cells that differ, leave the rest pooled with
    evidence that pooling is justified — which costs no coverage and is a natural third test
    in the family this function already corrects across. It is not implemented yet.
    """
    halves, halvesw = res["per"][name], res["perw"][name]
    h0, h1 = halves
    # `audit` is how the report accounts for a screen that now rejects: without the
    # candidate count beside the survivor count, a correction and a bug look the same.
    if audit is not None:
        audit["players"] += 1
    h0w, h1w = halvesw

    # Pass 1: every cell the screen looks at, per discovery fold, with its p-value. The
    # pooled support gates stay exactly as they were, so nothing ships on less total
    # evidence than before — the fold gates are additional, and roughly halve to match.
    cand: dict = {0: [], 1: []}
    shared: dict = {}          # (state, resp) -> field quantities, computed once
    for state in set(h0) | set(h1):
        mine = h0[state] + h1[state]
        n_pool = mine.total()
        if n_pool < MIN_STATE:
            continue
        base = res["field"][state] - mine
        bn = base.total()
        if bn < MIN_FIELD:
            continue
        # The player's own answer to this ball across all their responses to it — the
        # reference the payoff is read against, shrunk toward the field's rate for the
        # same state on the same pseudo-counts as `conv`, so the two are comparable.
        mine_w = h0w[state] + h1w[state]
        p_state = (res["fieldw"][state] - mine_w).total() / bn
        for resp, c_pool in mine.items():
            bf = base.get(resp, 0)
            if c_pool < MIN_CELL or bf < 20:
                continue
            p_field = bf / bn
            fconv = (res["fieldw"][state].get(resp, 0)
                     - (h0w[state][resp] + h1w[state][resp])) / bf
            # Era-standardized where the eras this player played in are thick enough to
            # price; pooled otherwise. A zero standardized share means the field of their
            # own era never played this at all, which the lift cannot divide by — that
            # falls back too rather than reporting an infinite lift. The baseline is
            # deliberately identical for both folds: it is what the player is being
            # compared against, not something the screen is selecting on.
            e_share, e_fconv, covered = era_baseline(res, name, state, resp)
            if e_share and covered >= ERA_COV_MIN * n_pool:
                p_field = e_share
                if e_fconv is not None:
                    fconv = e_fconv
            shared[(state, resp)] = (p_field, fconv, p_state)
            for disc in (0, 1):
                n_d, c_d = halves[disc][state].total(), halves[disc][state][resp]
                if n_d < FOLD_STATE or c_d < FOLD_CELL:
                    continue
                cand[disc].append((state, resp, binom_tail(c_d, n_d, p_field),
                                   shrunk_lift(c_d, n_d, p_field)))

    if audit is not None:
        audit["candidates"] += len(cand[0]) + len(cand[1])

    # Pass 2: correct inside the discovery fold, then confirm on the other one. The
    # correction family is every cell that fold could test, not just the ones that went
    # on to clear the lift gate — a candidate the screen looked at and turned away is not
    # free, and leaving it out would count a search over hundreds as a search over three.
    confirmed: dict = defaultdict(list)
    for disc in (0, 1):
        items = cand[disc]
        if not items:
            continue
        for (state, resp, _pv, dlift), q in zip(items, bh([c[2] for c in items])):
            if q > Q_FDR or dlift < LIFT_MIN:
                continue
            val = 1 - disc
            n_v, c_v = halves[val][state].total(), halves[val][state][resp]
            if n_v < FOLD_STATE or c_v < FOLD_CELL:
                continue
            if shrunk_lift(c_v, n_v, shared[(state, resp)][0]) < VAL_LIFT_MIN:
                continue
            confirmed[(state, resp)].append((val, dlift, q, len(items)))

    # Pass 3: the figures, off the fold(s) that did not do the selecting.
    out = []
    for (state, resp), hits in confirmed.items():
        p_field, fconv, p_state = shared[(state, resp)]
        used = (0, 1) if len(hits) == 2 else (hits[0][0],)
        n = sum(halves[f][state].total() for f in used)
        c = sum(halves[f][state][resp] for f in used)
        wins = sum(halvesw[f][state][resp] for f in used)
        state_wins = sum(halvesw[f][state].total() for f in used)
        lift = shrunk_lift(c, n, p_field)
        conv = (wins + K_CONV * fconv) / (c + K_CONV)
        sconv = (state_wins + K_CONV * p_state) / (n + K_CONV)
        out.append((c * np.log2(lift), lift, state, resp, n, c,
                    sum(h[1] for h in hits) / len(hits), len(hits),
                    conv, fconv, p_field, sconv,
                    min(h[2] for h in hits), max(h[3] for h in hits)))
    out.sort(reverse=True)
    rally = [p for p in out if p[2][0] == "rally"][:TOP_PER_PLAYER]
    ret = [p for p in out if p[2][0] == "ret"][:TOP_RETURN]
    if audit is not None:
        audit["confirmed"] += sum(len(h) for h in confirmed.values())
        audit["cells"] += len(confirmed)
        audit["surfaced"] += len(rally) + len(ret)
    return rally + ret


def stability_cells(res, min_half=40, min_total=10, k=15):
    """Per-half shrunk log-lifts for every well-populated cell — the honesty check."""
    xs, ys = [], []
    for _name, (h0, h1) in res["per"].items():
        for state in set(h0) & set(h1):
            c0, c1 = h0[state], h1[state]
            n0, n1 = c0.total(), c1.total()
            if n0 < min_half or n1 < min_half:
                continue
            base = res["field"][state] - c0 - c1
            bn = base.total()
            if bn < MIN_FIELD:
                continue
            for resp in set(c0) | set(c1):
                if c0[resp] + c1[resp] < min_total:
                    continue
                bf = base.get(resp, 0)
                if bf < 20:
                    continue
                p_field = bf / bn
                xs.append(np.log2(shrunk_lift(c0[resp], n0, p_field, k)))
                ys.append(np.log2(shrunk_lift(c1[resp], n1, p_field, k)))
    return np.array(xs), np.array(ys)


def state_name(state):
    fam, kind, zone, depth = state
    if fam == "ret":
        return f"{DEPTH_WORD[depth]} {INC_WORD[kind]} return into {ZONE_WORD[zone]}"
    return f"{INC_WORD[kind]} into {ZONE_WORD[zone]}"


def resp_name(zone, resp):
    """Plain-language name for a response, given the zone the incoming ball landed in.

    The line a shot takes is only half of its name; the other half is where it was
    struck from, which is why this needs the zone. Following the charting project's
    own definitions: crosscourt runs from the middle or a far corner to the opposite
    far corner, down the line starts in a corner and finishes in that same one, and
    inside-out is any ball hit against the crosscourt lane its wing opens onto. A ball
    met in the middle third therefore has no down the line available to it at all —
    there is no corner behind it to line up with — so the two ways out of the middle
    are crosscourt and, against it, inside-out.

    Run-arounds keep their own pair: inside-out on the diagonal, inside-in down the
    line. Only drives and slices get them, because the words describe a player stepping
    round the ball to hit a groundstroke, not a volley taken wherever it was reachable.

    Shared with the serve+1 experiment, which names the same responses from the same
    zones. It takes the zone rather than a state because the two experiments carry
    different state shapes over the identical geometry.
    """
    wing, kind, line = resp
    word = RESP_WORD[kind]
    if line == "mid":
        return f"{wing} {word} through the middle"
    if zone == "mid":
        return (f"crosscourt {wing} {word}" if line == "cc"
                else f"inside-out {wing} {word}")
    if zone != wing.lower() and kind in ("drive", "slice"):
        return f"{'inside-out' if line == 'cc' else 'inside-in'} {wing} {word}"
    return f"crosscourt {wing} {word}" if line == "cc" else f"{wing} {word} down the line"


def physical_codes(state, resp, hand):
    """Map a (state, resp) back to physical zone codes for this player, so the
    site's court renderer can draw the pattern later."""
    zone, (wing, _kind, line) = state[2], resp
    inc = "2" if zone == "mid" else {"R": {"fh": "1", "bh": "3"},
                                     "L": {"fh": "3", "bh": "1"}}[hand][zone]
    ref = inc if inc != "2" else WING_LANE[hand][wing]
    out = ref if line == "cc" else (MIRROR[ref] if line == "dtl" else "2")
    return inc, out


def old_signature_sharing():
    """Distinctiveness of the current site signatures, for comparison."""
    path = REPORTS / "shot_language_players.csv"
    if not path.exists():
        return None
    import re
    pairs, n_players = Counter(), 0
    with open(path) as fh:
        for row in csv.DictReader(fh):
            n_players += 1
            for s in row["signatures"].split("; "):
                if s:
                    pairs[re.sub(r" \(\d+\.\d+x\)$", "", s)] += 1
    if not pairs:
        return None
    top, cnt = pairs.most_common(1)[0]
    return dict(n_players=n_players, top=top, cnt=cnt)


def fig_stability(results, path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    for ax, g in zip(axes, ("M", "W")):
        xs, ys = results[g]["stab"]
        r = np.corrcoef(xs, ys)[0, 1]
        lim = max(np.abs(np.concatenate([xs, ys]))) * 1.05
        ax.plot([-lim, lim], [-lim, lim], color="gray", lw=0.8, ls=":")
        ax.scatter(xs, ys, s=4, alpha=0.15, color="#2ca02c")
        ax.set_xlabel("log2 lift — half 1 of a player's matches")
        ax.set_ylabel("log2 lift — half 2")
        ax.set_title(f"{GLABEL[g]} — r = {r:+.2f} ({len(xs):,} cells)")
        ax.set_xlim(-lim, lim)
        ax.set_ylim(-lim, lim)
    fig.suptitle("Do court-state response tendencies repeat across a career split in half?")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    hands = hand_map(con)
    results = {g: analyze(con, g, hands) for g in ("M", "W")}
    con.close()

    for g in ("M", "W"):
        results[g]["stab"] = stability_cells(results[g])
    fig_stability(results, FIG / "court_response_stability.png")

    # Per-player export: one row per surfaced pattern.
    rows = []
    audit = {g: Counter() for g in ("M", "W")}
    for g in ("M", "W"):
        r = results[g]
        # Sorted, so the emitted row order is a property of the data rather than of
        # the order DuckDB happened to hand back the scan.
        for name in sorted(r["per"]):
            hand = hands[name]
            for (ev, lift, state, resp, n, c, disc_lift, folds,
                 conv, fconv, pf, sconv, q, ncand) in profile(r, name, audit[g]):
                inc, out = physical_codes(state, resp, hand)
                rows.append(dict(
                    player=name, gender=g, hand=hand, family=state[0],
                    state=state_name(state), response=resp_name(state[2], resp),
                    state_kind=state[1], state_zone=state[2],
                    state_depth=DEPTH_WORD.get(state[3], ""),
                    resp_wing=resp[0], resp_kind=resp[1], resp_line=resp[2],
                    inc_code=inc, resp_code=out,
                    n_state=n, count=c, lift=round(lift, 2),
                    evidence=round(ev, 1),
                    disc_lift=round(disc_lift, 2), folds=folds,
                    p_bh=round(q, 4), n_candidates=ncand,
                    field_share=round(pf, 4), state_win_rate=round(sconv, 3),
                    win_rate=round(conv, 3), tour_win_rate=round(fconv, 3)))
    with open(REPORTS / "court_response_players.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # Distinctiveness: how shared is each player's top surfaced pattern?
    md = ["# Court-state response profiles", ""]
    md.append("*Generated by `experiments/court_response/run.py`. The state is the "
              "incoming ball only — its character and the zone it lands in, named "
              "relative to the receiver's own hands — and the response is the "
              "player's decision: wing, shot type, and line. Lift compares the "
              "player's response rate in that state to the rest of the field in the "
              "same state (their own shots excluded), shrunk toward 1 by "
              f"{K_SHRINK} pseudo-counts. **Every figure shown is held out.** A player's "
              "matches are split in two; each fold takes a turn discovering, with an exact "
              "binomial tail against the field's share and a Benjamini-Hochberg correction "
              f"at q={Q_FDR:g} across every cell that fold screened for that player; the "
              "lift, payoff and counts are then read off the other fold, which had no part "
              f"in the selection. Support floors: n≥{MIN_STATE} in the state and "
              f"count≥{MIN_CELL} pooled, n≥{FOLD_STATE} and count≥{FOLD_CELL} within each "
              f"fold, shrunk lift≥{LIFT_MIN} where it was found and ≥{VAL_LIFT_MIN} where "
              "it was measured. Patterns are ranked by evidence (count x log2 lift), so a "
              "bread-and-butter tendency outranks a rare quirk with a flashier lift. "
              "Uncharted directions and unknown wings are excluded outright. Each "
              "pattern carries its payoff: the player's point-win rate after playing "
              f"that response (shrunk toward the field's by {K_CONV} pseudo-counts) "
              "next to the field's own rate playing the same response to the same "
              "ball — lift is the choice, payoff is what it earns.*")
    md.append("")

    # What the screen rejects, said out loud. A correction that halves a table and a bug
    # that halves a table produce the same number; only the candidate count separates them.
    md.append("## What the screen turns away")
    md.append("")
    md.append("Without a multiplicity correction, and reading the lift off the same data "
              "the gates used to select the pattern, this table would be a search rather "
              "than a test. The accounting for the screen that runs instead:")
    md.append("")
    md.append("| | players screened | candidates tested | directions confirmed | surfaced |")
    md.append("|---|--:|--:|--:|--:|")
    for g in ("M", "W"):
        a = audit[g]
        md.append(f"| {GLABEL[g]} | {a['players']:,} | {a['candidates']:,} | "
                  f"{a['confirmed']:,} | {a['surfaced']:,} |")
    md.append("")
    df = pd.DataFrame(rows)
    one = df[df.folds == 1]
    both = df[df.folds == 2]
    if len(one):
        md.append("**What the winner's curse was worth here.** For the "
                  f"{len(one):,} patterns confirmed from a single direction — where the "
                  "displayed lift comes from a fold with no vote in the selection — the "
                  f"mean discovery lift is {one.disc_lift.mean():.2f}x and the mean "
                  f"displayed lift is {one.lift.mean():.2f}x, so "
                  f"**{(one.lift.mean() - 1) / (one.disc_lift.mean() - 1):.0%} of the "
                  "discovered edge survives out of sample**. That is close to what "
                  "`rally_patterns` measured on a different screen over different "
                  "features (50%), which is some evidence it is a property of this kind "
                  "of search rather than of either experiment.")
        md.append("")
        md.append(f"The other {len(both):,} patterns cleared from both directions, each "
                  "fold validating the other, and show the two halves pooled — so their "
                  "displayed lift is not a clean out-of-sample read and is not quoted as "
                  "one. Being findable twice independently is itself the stronger claim.")
        md.append("")
    md.append("The correction is cheap here: it takes this table from 2,804 patterns "
              f"over 805 players to {len(df):,} over {df.player.nunique():,}. The "
              "split-half r below is why — these cells were already stable, so "
              "correcting them mostly removes the thin tail rather than the findings.")
    md.append("")
    md.append("**Still pooled, and known to be:** a cell counts the serve+1 ball together "
              "with the same-described ball at shot 11. For 691 of 4,218 well-supported "
              "cells (16.4%, against 0 of 5,040 on a coin-flip control) the response a "
              "player picks differs measurably between the two, so those cells are "
              "reporting an average of two situations and naming neither. Splitting them "
              "is not implemented; the 16.4% is measured so the profiles can be read "
              "knowing it.")
    md.append("")

    old = old_signature_sharing()
    for g in ("M", "W"):
        r = results[g]
        f = r["funnel"]
        prof = {n: profile(r, n) for n in r["per"]}
        prof = {n: p for n, p in prof.items() if p}
        rally_heads = [p[0] for p in prof.values() if p[0][2][0] == "rally"]
        share = Counter((h[2], h[3]) for h in rally_heads)
        xs, ys = r["stab"]
        stab_r = np.corrcoef(xs, ys)[0, 1]

        md.append(f"## {GLABEL[g]}")
        md.append("")
        md.append(f"- {f['points']:,} points → {f['parsed']:,} parsed → "
                  f"{f['pairs']:,} rally-shot pairs → {f['obs']:,} usable "
                  f"observations, {f['ret_obs']:,} of them shot-3 responses "
                  "to a depth-charted return.")
        md.append(f"- {len(prof):,} players clear the gates with at least one "
                  "stable pattern.")
        md.append(f"- **Split-half stability**: r = {stab_r:+.2f} across "
                  f"{len(xs):,} player-state-response cells — the tendencies "
                  "repeat in the other half of the same player's matches.")
        if share:
            (ts, tr), tc = share.most_common(1)[0]
            md.append(f"- **Distinctiveness**: the most-shared headline pattern "
                      f"({state_name(ts)} → {resp_name(ts[2], tr)}) tops "
                      f"{tc} of {len(prof)} profiles ({tc / len(prof):.0%}).")
        md.append("")

        vol = sorted(prof, key=lambda n: -sum(p[4] for p in prof[n]))
        md.append("**Highest-volume profiles** (lift vs the field in the same state; "
                  "the discovery-fold lift in parentheses):")
        md.append("")
        for name in vol[:8]:
            parts = [f"{state_name(st)} → **{resp_name(st[2], rp)}** "
                     f"({lift:.1f}x vs {pf:.0%} of the era-matched field, "
                     f"n={c}/{n} held out, found at {dl:.1f}x, "
                     f"wins {cv:.0%} vs {sc:.0%} on this ball overall, "
                     f"tour {fc:.0%})"
                     for _ev, lift, st, rp, n, c, dl, _fd, cv, fc, pf, sc, _q, _nc
                     in prof[name] if st[0] == "rally"]
            md.append(f"- **{name}** ({hands[name]}): " + "; ".join(parts))
        md.append("")

        rets = sorted(((p, nm) for nm, pats in prof.items() for p in pats
                       if p[2][0] == "ret"), reverse=True)
        md.append("**Off the return** (the server's shot 3, by charted return "
                  "depth — strongest evidence first, one per player):")
        md.append("")
        seen = set()
        for (ev, lift, st, rp, n, c, dl, _fd, cv, fc, pf, sc, _q, _nc), name in rets:
            if name in seen:
                continue
            seen.add(name)
            md.append(f"- **{name}**: {state_name(st)} → **{resp_name(st[2], rp)}** "
                      f"({lift:.1f}x vs {pf:.0%} of the era-matched field, "
                      f"n={c}/{n} held out, found at {dl:.1f}x, "
                      f"wins {cv:.0%} vs {sc:.0%} on this ball overall, tour {fc:.0%})")
            if len(seen) >= 6:
                break
        md.append("")

    md.append("## Against the current signature panel")
    md.append("")
    if old:
        md.append(f"- The site's signatures: the single most-shared pair "
                  f"(`{old['top']}`) appears on {old['cnt']} of "
                  f"{old['n_players']} player cards "
                  f"({old['cnt'] / old['n_players']:.0%}).")
    md.append("- Here, uncharted-direction artifacts are excluded by construction, "
              "handedness is normalized out of the state, and the split-half gate "
              "drops anything that does not repeat.")
    md.append("")
    md.append("![stability](figures/court_response_stability.png)")
    md.append("")
    md.append("## Next steps")
    md.append("")
    md.append("- An outcome layer per pattern (how often the response wins the point "
              "vs the field's outcomes from the same state), mirroring the trigger "
              "experiment's frequency/conversion split.")
    md.append("- Separate the drop shot and lob out of the drop/lob bucket once "
              "counts allow.")
    md.append("- Depth beyond shot 3 if charting coverage ever improves (only ~19% "
              "of later rally balls carry a depth code).")
    md.append("")
    (REPORTS / "court_response.md").write_text("\n".join(md))
    print(f"wrote reports/court_response.md and court_response_players.csv "
          f"({len(rows)} patterns)")


if __name__ == "__main__":
    main()
