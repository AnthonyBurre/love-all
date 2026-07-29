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
(crosscourt / down the line / middle). Everything upstream of the incoming ball
is deliberately ignored.

Zone geometry: direction codes name fixed thirds ("1" = a right-hander's
forehand corner), and the two ends face each other, so a reply to the *same*
code travels the diagonal (crosscourt) and a reply to the mirrored code goes
down the line. For balls arriving through the middle, the hitter's wing fixes
the reference lane. Run-around shots (e.g. a forehand played from the backhand
corner) get their tennis names: inside-out on the diagonal, inside-in down the
line.

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

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import parse_point, stroke_kind  # noqa: E402

REPORTS = PROJECT_ROOT / "reports"
FIG = REPORTS / "figures"
GLABEL = {"M": "Men", "W": "Women"}

# Surfacing gates (all documented in the report).
MIN_STATE = 80        # times a player must face a state to be profiled on it
MIN_CELL = 10         # raw count behind any surfaced response
MIN_FIELD = 500       # field observations of the state (minus the player's own)
K_SHRINK = 30         # pseudo-count pull toward the field distribution
K_CONV = 20           # pseudo-count pull of a pattern's win rate toward the field's
LIFT_MIN = 1.4        # shrunk lift needed to surface
HALF_LIFT_MIN = 1.15  # raw lift required in *both* halves of their matches
HALF_MIN = 4          # raw count required in both halves
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


def analyze(con, gender, hands):
    field = defaultdict(Counter)   # state -> Counter(resp)
    fieldw = defaultdict(Counter)  # state -> Counter(resp) of points won
    per = defaultdict(lambda: (defaultdict(Counter), defaultdict(Counter)))
    perw = defaultdict(lambda: (defaultdict(Counter), defaultdict(Counter)))
    funnel = Counter()
    res = con.execute(
        "SELECT m.player1, m.player2, p.match_id, p.svr, p.first_serve, "
        "p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?", [gender])
    while batch := res.fetchmany(50_000):
        for p1, p2, mid, svr, fs, ss, win in batch:
            funnel["points"] += 1
            pt = parse_point(fs, ss, svr, win)
            if not pt.parse_ok:
                continue
            funnel["parsed"] += 1
            half = zlib.crc32(str(mid).encode()) & 1
            names = {1: p1, 2: p2}
            for name, hand, state, resp, won in observations(pt, names, hands, funnel):
                field[state][resp] += 1
                fieldw[state][resp] += won
                per[name][half][state][resp] += 1
                perw[name][half][state][resp] += won
    return dict(field=field, fieldw=fieldw, per=per, perw=perw, funnel=funnel)


def shrunk_lift(c, n, p_field, k=K_SHRINK):
    return ((c + k * p_field) / (n + k)) / p_field


def profile(res, name):
    """A player's surfaced patterns:
    (ev, lift, state, resp, n_state, c, l0, l1, conv, fconv).

    Ranked by evidence = count x log2(lift), the cell's contribution to the
    player's divergence from the field — raw lift alone crowns rare quirks
    (a 5x lift on 60 of 29,000 balls) over bread-and-butter tendencies.
    ``conv`` is the player's point-win rate playing that response (shrunk
    toward the field's by K_CONV pseudo-counts); ``fconv`` is the field's,
    same state and response, the player's own points excluded.
    """
    h0, h1 = res["per"][name]
    h0w, h1w = res["perw"][name]
    out = []
    for state in set(h0) | set(h1):
        c0, c1 = h0[state], h1[state]
        mine = c0 + c1
        n = mine.total()
        if n < MIN_STATE:
            continue
        base = res["field"][state] - mine
        bn = base.total()
        if bn < MIN_FIELD:
            continue
        for resp, c in mine.items():
            bf = base.get(resp, 0)
            if c < MIN_CELL or bf < 20:
                continue
            p_field = bf / bn
            lift = shrunk_lift(c, n, p_field)
            if lift < LIFT_MIN:
                continue
            if min(c0[resp], c1[resp]) < HALF_MIN:
                continue
            l0 = (c0[resp] / c0.total()) / p_field
            l1 = (c1[resp] / c1.total()) / p_field
            if min(l0, l1) < HALF_LIFT_MIN:
                continue
            wins = h0w[state][resp] + h1w[state][resp]
            fconv = (res["fieldw"][state].get(resp, 0) - wins) / bf
            conv = (wins + K_CONV * fconv) / (c + K_CONV)
            out.append((c * np.log2(lift), lift, state, resp, n, c, l0, l1,
                        conv, fconv))
    out.sort(reverse=True)
    rally = [p for p in out if p[2][0] == "rally"][:TOP_PER_PLAYER]
    ret = [p for p in out if p[2][0] == "ret"][:TOP_RETURN]
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


def resp_name(state, resp):
    wing, kind, line = resp
    word = RESP_WORD[kind]
    if line == "mid":
        return f"{wing} {word} through the middle"
    run_around = (state[2] in ("fh", "bh") and state[2] != wing.lower()
                  and kind in ("drive", "slice"))
    if run_around:
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
    for g in ("M", "W"):
        r = results[g]
        for name in r["per"]:
            hand = hands[name]
            for ev, lift, state, resp, n, c, l0, l1, conv, fconv in profile(r, name):
                inc, out = physical_codes(state, resp, hand)
                rows.append(dict(
                    player=name, gender=g, hand=hand, family=state[0],
                    state=state_name(state), response=resp_name(state, resp),
                    state_kind=state[1], state_zone=state[2],
                    state_depth=DEPTH_WORD.get(state[3], ""),
                    resp_wing=resp[0], resp_kind=resp[1], resp_line=resp[2],
                    inc_code=inc, resp_code=out,
                    n_state=n, count=c, lift=round(lift, 2),
                    evidence=round(ev, 1),
                    lift_h1=round(l0, 2), lift_h2=round(l1, 2),
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
              f"{K_SHRINK} pseudo-counts. A pattern is surfaced only with "
              f"n≥{MIN_STATE} in the state, count≥{MIN_CELL}, shrunk lift≥{LIFT_MIN}, "
              f"and raw lift≥{HALF_LIFT_MIN} in both halves of the player's charted "
              "matches. Patterns are ranked by evidence (count x log2 lift), so a "
              "bread-and-butter tendency outranks a rare quirk with a flashier lift. "
              "Uncharted directions and unknown wings are excluded outright. Each "
              "pattern carries its payoff: the player's point-win rate after playing "
              f"that response (shrunk toward the field's by {K_CONV} pseudo-counts) "
              "next to the field's own rate playing the same response to the same "
              "ball — lift is the choice, payoff is what it earns.*")
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
                      f"({state_name(ts)} → {resp_name(ts, tr)}) tops "
                      f"{tc} of {len(prof)} profiles ({tc / len(prof):.0%}).")
        md.append("")

        vol = sorted(prof, key=lambda n: -sum(p[4] for p in prof[n]))
        md.append("**Highest-volume profiles** (lift vs the field in the same state; "
                  "both-halves lifts in parentheses):")
        md.append("")
        for name in vol[:8]:
            parts = [f"{state_name(st)} → **{resp_name(st, rp)}** "
                     f"({lift:.1f}x, n={c}/{n}, halves {l0:.1f}/{l1:.1f}, "
                     f"wins {cv:.0%} vs {fc:.0%})"
                     for _ev, lift, st, rp, n, c, l0, l1, cv, fc in prof[name]
                     if st[0] == "rally"]
            md.append(f"- **{name}** ({hands[name]}): " + "; ".join(parts))
        md.append("")

        rets = sorted(((p, nm) for nm, pats in prof.items() for p in pats
                       if p[2][0] == "ret"), reverse=True)
        md.append("**Off the return** (the server's shot 3, by charted return "
                  "depth — strongest evidence first, one per player):")
        md.append("")
        seen = set()
        for (ev, lift, st, rp, n, c, l0, l1, cv, fc), name in rets:
            if name in seen:
                continue
            seen.add(name)
            md.append(f"- **{name}**: {state_name(st)} → **{resp_name(st, rp)}** "
                      f"({lift:.1f}x, n={c}/{n}, halves {l0:.1f}/{l1:.1f}, "
                      f"wins {cv:.0%} vs {fc:.0%})")
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
              "experiment's attempt/conversion split.")
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
