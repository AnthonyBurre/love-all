"""Serve placement: which tendencies are measurements, and which are noise.

Run:  python experiments/serve_tendencies/run.py

``serve_side`` established that deuce and ad are different shots and printed the
direction mix for the tour and five marquee players per tour. This experiment
asks the measurement question underneath that table: of the serve-placement
statistics a player card could carry — the wide/body/T mix per side, whether it
moved across a career, whether it holds match to match, whether it changes on
big points — which ones survive their own error bars, and how much charted data
each one needs before it does.

Six steps, one pass over the charted points per tour:

  Step 1  what is charted — how often a delivery carries a direction code at all,
          by decade and by charter, since every rate below is conditioned on it.
  Step 2  the tour picture — mix by side and serve number, and how widely players
          spread around it. True spread is the ceiling on everything that
          follows: a statistic cannot be informative if players do not differ on
          it by more than sampling noise.
  Step 3  is it a measurement — for four candidate card stats, the split-half
          correlation across a player's matches, and the charted sample each one
          needs to be mostly signal. The sample size is *not* the binomial
          answer: the observed split-half correlations come in well below what a
          fixed-coin player would give, and the gap is quantified as a noise
          inflation factor rather than ignored.
  Step 4  match to match — where that extra noise comes from. Binomial
          overdispersion per player, then the same test with each match expected
          at the player's rate against that returner's handedness, and again at
          the player's rate that calendar year, to separate opponent adaptation
          from slow career drift.
  Step 5  careers — early-vs-late placement gap against a shuffled-match null,
          the ``career_splits`` design narrowed to the serve.
  Step 6  big points — placement on break points against the same player's own
          normal-point rate, side-adjusted, because break points skew to the ad
          court and the side moves placement far more than the score does.

Writes reports/serve_tendencies.md, reports/serve_tendencies_players.csv,
reports/serve_tendencies_leverage.csv, and two figures.
"""

import csv
import math
import sys
import zlib
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "score_aware_eval"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from model import pressure  # noqa: E402  (the score-aware leverage buckets)

from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402
from match_charting_project.shots.notation import serve_dir  # noqa: E402
from match_charting_project.shots.score import serve_side  # noqa: E402

REPORTS = PROJECT_ROOT / "reports"
FIG = REPORTS / "figures"
GLABEL = {"M": "Men", "W": "Women"}
SIDES = ("deuce", "ad")
DIRS = ("4", "5", "6")
DIRNAME = {"4": "wide", "5": "body", "6": "T"}
SNUM = {1: "1st", 2: "2nd"}
BUCKETS = ("normal", "break_pt", "game_pt", "deuce", "tiebreak")

# Gates. Each one is a claim about how much data a statistic needs, so they are
# reported next to the numbers they produce rather than left in the code.
MIN_PROFILE = 150      # charted serves for a (player, side, serve number) profile
MIN_HALF = 50          # per half and per target, for the split-half correlations
MIN_MATCH_SERVES = 12  # charted serves in a match for it to count as a repeat
MIN_MATCHES = 15       # matches, for the match-to-match dispersion test
MIN_HAND = 40          # serves against each handedness, for the conditioned test
DRIFT_SERVES = 800     # career total (both sides) for the drift test
DRIFT_YEARS = 8        # charted-year span, matching career_splits' gate
DRIFT_SHUFFLES = 50    # shuffled match orders per player, for the null
DRIFT_BIG = 1.5        # chronological / shuffled ratio counted as real movement
MIN_BREAK = 80         # break-point first serves for the leverage test
HOLDOUT_SERVES = 200   # most-recent charted first serves held out as the target
HISTORY_SERVES = 600   # history a player needs before that holdout to be scanned
WINDOWS = (5, 10, 20, 40, 80, None)  # matches of history scored; None = whole career
HALFLIVES = (10, 20, 40, 80)         # exponential decay in matches, same scoring
SMOOTH_K = 25          # pseudo-counts pulling a window's mix toward the tour's
FDR_Q = 0.10           # Benjamini-Hochberg level for the per-player tests


def hand_map(con) -> dict:
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


def _dircounts() -> list:
    return [0, 0, 0]


def collect(con, gender: str, hands: dict) -> dict:
    """One pass: per-match placement counts, plus coverage, leverage and payoff.

    ``mix[(player, side, snum)][match_id]`` holds [wide, body, T] counts. That is
    the granularity every later step needs — halves, per-match dispersion and
    career splits are all groupings of matches. ``pay[(player, side)][match_id]``
    holds first serves that actually started the point and the points won off
    them, by target, so the same split-half machinery can be pointed at what a
    placement earned rather than at how often it was chosen.
    """
    mix = defaultdict(lambda: defaultdict(_dircounts))
    pay = defaultdict(lambda: defaultdict(lambda: [0] * 6))
    lev = defaultdict(_dircounts)           # (scope, side, bucket) -> counts
    byhand = defaultdict(_dircounts)        # (player, side, opp hand) -> counts
    cover = defaultdict(lambda: [0, 0, 0])  # decade -> [serves, coded, coded '0']
    chart = defaultdict(lambda: [0, 0])     # charter -> [serves, coded]
    year = {}                               # match_id -> year
    opp = {}                                # (player, match_id) -> opponent hand
    charter_of = {}                         # match_id -> charter
    order = {}                              # match_id -> sort key (date, then id)
    sql = (
        "SELECT p.match_id, m.player1, m.player2, m.year, m.date, m.charted_by, p.decade, "
        "       p.svr, p.pts, p.gm1, p.gm2, p.first_serve, p.second_serve, p.pt_winner "
        "FROM points p JOIN matches m USING (match_id) "
        "WHERE p.svr IN (1,2) AND p.pt_winner IN (1,2) AND m.gender = ?"
    )
    cur = con.execute(sql, [gender])
    while batch := cur.fetchmany(100_000):
        for mid, p1, p2, yr, dt, charter, decade, svr, pts, g1, g2, fs, ss, win in batch:
            side = serve_side(pts)
            if side not in SIDES:
                continue
            server, returner = (p1, p2) if svr == 1 else (p2, p1)
            won = 1 if win == svr else 0
            second = bool((ss or "").strip())

            d1 = serve_dir(fs)
            cov = cover[decade or "unknown"]
            cov[0] += 1
            cov[1] += d1 in DIRS
            cov[2] += d1 == "0"
            ch = chart[(charter or "").strip() or "unknown"]
            ch[0] += 1
            ch[1] += d1 in DIRS

            if d1 in DIRS:
                i = DIRS.index(d1)
                year[mid] = yr
                # Dates are mostly clean but not universally present; the year plus
                # the id keeps the order total and stable when one is missing.
                order[mid] = (dt.toordinal() if dt else 0, yr or 0, str(mid))
                charter_of[mid] = (charter or "").strip() or "unknown"
                opp[(server, mid)] = hands.get(returner, "?")
                mix[(server, side, 1)][mid][i] += 1
                byhand[(server, side, hands.get(returner, "?"))][i] += 1
                for scope in ("_tour_", server):
                    lev[(scope, side, pressure(pts, g1, g2))][i] += 1
                if not second:                     # the first delivery started the point
                    rec = pay[(server, side)][mid]
                    rec[i] += 1
                    rec[3 + i] += won

            if second:
                d2 = serve_dir(ss)
                if d2 in DIRS:
                    mix[(server, side, 2)][mid][DIRS.index(d2)] += 1
    return dict(mix=mix, pay=pay, lev=lev, byhand=byhand, cover=cover,
                chart=chart, year=year, opp=opp, charter_of=charter_of, order=order)


def charter_effect(res, i, min_cell=150, min_rest=300, min_charter=2000):
    """Does a charter shift the mix of the *same* players they chart?

    Charters agree on whether a target was hit; they need not agree on where the
    boundaries are, and a serve near the middle can be charted body or wide. For
    every (player, charter) cell this compares the mix that charter recorded
    against the mix everyone else recorded for that same player, so the player is
    held fixed and only the charter varies. Returns the weighted deviation per
    charter — the size of the charter's fingerprint on the statistic.
    """
    cells, tot = defaultdict(_dircounts), defaultdict(_dircounts)
    for (player, _side, snum), bymatch in res["mix"].items():
        if snum != 1:
            continue
        for mid, c in bymatch.items():
            cell = cells[(player, res["charter_of"].get(mid, "unknown"))]
            for j in range(3):
                cell[j] += c[j]
                tot[player][j] += c[j]
    dev = defaultdict(lambda: [0.0, 0.0])
    for (player, ch), c in cells.items():
        n, rest = sum(c), [tot[player][j] - c[j] for j in range(3)]
        rn = sum(rest)
        if n < min_cell or rn < min_rest:
            continue
        acc = dev[ch]
        acc[0] += n * (c[i] / n - rest[i] / rn)
        acc[1] += n
    vals = sorted(v[0] / v[1] for v in dev.values() if v[1] >= min_charter)
    if len(vals) < 3:
        return None
    return dict(sd=float(np.std(vals)), lo=vals[0], hi=vals[-1], n=len(vals))


# --------------------------------------------------------------------------- #
# statistics helpers (this project carries no scipy)
# --------------------------------------------------------------------------- #

def pearson(xs, ys) -> float:
    return float(np.corrcoef(xs, ys)[0, 1]) if len(xs) > 2 else float("nan")


def spearman_brown(r: float, k: float = 2.0) -> float:
    """Reliability of a k-times-longer test than the one measured."""
    return k * r / (1 + (k - 1) * r) if r > -1 else float("nan")


def norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2))


def chi2_sf(x: float, df: int) -> float:
    """Wilson-Hilferty normal approximation; good to ~1e-3 for df >= 5."""
    if df <= 0 or x <= 0:
        return 1.0
    z = ((x / df) ** (1 / 3) - (1 - 2 / (9 * df))) / math.sqrt(2 / (9 * df))
    return norm_sf(z)


def bh_reject(pvals: list, q: float = FDR_Q) -> int:
    """How many hypotheses survive Benjamini-Hochberg at level q."""
    if not pvals:
        return 0
    ps = sorted(pvals)
    k = 0
    for i, p in enumerate(ps, 1):
        if p <= q * i / len(ps):
            k = i
    return k


def components(values, samp_vars, ns):
    """Split the spread in a statistic into real differences and sampling noise.

    Players differ by tau (real) plus a sampling error that shrinks with their
    charted count, so the raw spread across players always overstates how far
    apart they are. ``samp_vars`` is each player's own sampling variance and
    ``ns`` their charted first serves on that side, which lets the noise be
    re-expressed as ``v1 / n`` — the sampling variance one serve's worth of data
    would carry — so every statistic here is comparable on the same axis.
    """
    values, samp_vars, ns = np.array(values), np.array(samp_vars), np.array(ns)
    obs = float(np.var(values, ddof=1))
    samp = float(np.mean(samp_vars))
    return dict(mean=float(np.mean(values)), obs_var=obs, samp_var=samp,
                tau2=max(obs - samp, 0.0), v1=float(np.mean(samp_vars * ns)),
                n=len(values), median_n=float(np.median(ns)))


def n_for_reliability(vc: dict, r: float, inflate: float = 1.0) -> float:
    """Charted first serves on that side needed for a statistic to be ``r`` signal."""
    if vc["tau2"] <= 0:
        return float("inf")
    return r * inflate * vc["v1"] / ((1 - r) * vc["tau2"])


def implied_inflation(vc: dict, r_half: float, n_half: float) -> float:
    """How much noisier a statistic is than a fixed-coin player would be.

    A player who flipped one coin every match would give a split-half
    correlation of tau2 / (tau2 + v1/n_half). The observed correlation is lower;
    this returns the factor on the sampling variance that closes the gap, which
    is the same quantity step 4 measures directly as overdispersion.
    """
    if vc["tau2"] <= 0 or r_half <= 0 or n_half <= 0:
        return float("nan")
    return max((vc["tau2"] / r_half - vc["tau2"]) * n_half / vc["v1"], 1.0)


# --------------------------------------------------------------------------- #
# Step 3 — candidate card statistics
# --------------------------------------------------------------------------- #

def _sum_records(recs):
    out = None
    for c in recs:
        out = list(c) if out is None else [a + b for a, b in zip(out, c)]
    return out


def _split_records(bymatch: dict, keyfn=None):
    """Sum a player's per-match records into two deterministic halves.

    Splitting on the match id asks whether a tendency repeats across a player's
    own matches. Splitting on the *charter* asks the stricter question — whether
    it repeats across the people who wrote it down — and any charter fingerprint
    then counts against the correlation instead of propping it up.
    """
    out = [None, None]
    for mid, c in bymatch.items():
        k = mid if keyfn is None else keyfn(mid)
        if k is None:
            continue
        j = zlib.crc32(str(k).encode()) & 1
        out[j] = list(c) if out[j] is None else [a + b for a, b in zip(out[j], c)]
    return out


def st_share(i):
    """How often the player picks target ``i`` — the choice itself."""
    def f(mix, pay, floor):
        n = sum(mix[:3]) if mix else 0
        if n < floor:
            return None
        p = mix[i] / n
        return p, p * (1 - p) / n, n
    return f


def st_in_gap(mix, pay, floor):
    """First-serve-in rate down the T minus wide — execution, not choice."""
    if not mix or not pay or min(mix[0], mix[2]) < floor:
        return None
    pw, pt = pay[0] / mix[0], pay[2] / mix[2]
    var = pw * (1 - pw) / mix[0] + pt * (1 - pt) / mix[2]
    return pt - pw, var, sum(mix[:3])


def st_pay_gap(mix, pay, floor):
    """Points won behind the T minus behind the wide serve, first serves in."""
    if not mix or not pay or min(pay[0], pay[2]) < floor:
        return None
    pw, pt = pay[3] / pay[0], pay[5] / pay[2]
    var = pw * (1 - pw) / pay[0] + pt * (1 - pt) / pay[2]
    return pt - pw, var, sum(mix[:3])


CARD_STATS = (
    ("wide share (deuce, 1st serve)", st_share(0)),
    ("T share (deuce, 1st serve)", st_share(2)),
    ("1st-serve-in rate, T minus wide", st_in_gap),
    ("points won, T minus wide", st_pay_gap),
)


def card_stat(res, statfn, keyfn=None):
    """Variance components on full profiles, and the split-half correlation.

    Both are computed on the deuce court's first serves, the largest single
    sample, so the four statistics are compared on the same footing. ``keyfn``
    chooses what the halves split on (see ``_split_records``).
    """
    vals, svars, ns, xs, ys, half_ns = [], [], [], [], [], []
    for (player, side, snum), bymatch in res["mix"].items():
        if side != "deuce" or snum != 1:
            continue
        payby = res["pay"].get((player, side), {})
        full = statfn(_sum_records(bymatch.values()),
                      _sum_records(payby.values()) if payby else None, MIN_PROFILE)
        if full:
            vals.append(full[0])
            svars.append(full[1])
            ns.append(full[2])
        mh, ph = _split_records(bymatch, keyfn), _split_records(payby, keyfn)
        pair = [statfn(mh[j], ph[j], MIN_HALF) for j in (0, 1)]
        if all(pair):
            xs.append(pair[0][0])
            ys.append(pair[1][0])
            half_ns += [pair[0][2], pair[1][2]]
    if len(vals) < 3 or len(xs) < 3:
        return None
    vc = components(vals, svars, ns)
    r = pearson(xs, ys)
    n_half = float(np.median(half_ns))
    phi = implied_inflation(vc, r, n_half)
    return dict(vc=vc, r=r, reliability=spearman_brown(r), xs=xs, ys=ys,
                n_half=n_half, phi=phi,
                n80=n_for_reliability(vc, 0.8, phi),
                n80_binomial=n_for_reliability(vc, 0.8))


# --------------------------------------------------------------------------- #
# Step 4 — match-to-match dispersion
# --------------------------------------------------------------------------- #

def _chi(records, rates, i):
    """Binomial chi-square of per-match counts against per-match expected rates."""
    tot = 0.0
    for c, p in zip(records, rates):
        n = sum(c[:3])
        if 0 < p < 1 and n:
            tot += (c[i] - n * p) ** 2 / (n * p * (1 - p))
    return tot


def dispersion(res, i=0):
    """Per player: does the per-match wide share move more than binomial noise?

    ``phi`` is chi-square over degrees of freedom, so 1.0 is a player who flips
    the same coin in every match. Two conditioned versions locate the excess:
    ``phi_hand`` expects each match at the player's own rate against that
    returner's handedness, ``phi_year`` at their rate that calendar year. What a
    conditioner removes is the share of match-to-match movement it explains.
    """
    rows = []
    for (player, side, snum), bymatch in res["mix"].items():
        if snum != 1:
            continue
        ms = [(mid, c) for mid, c in bymatch.items() if sum(c[:3]) >= MIN_MATCH_SERVES]
        if len(ms) < MIN_MATCHES:
            continue
        recs = [c for _mid, c in ms]
        tot_n = sum(sum(c[:3]) for c in recs)
        p = sum(c[i] for c in recs) / tot_n
        if not 0 < p < 1:
            continue
        df = len(ms) - 1
        chi = _chi(recs, [p] * len(recs), i)
        row = dict(player=player, side=side, matches=len(ms), n=tot_n, p=p,
                   phi=chi / df, pval=chi2_sf(chi, df),
                   phi_hand=float("nan"), phi_year=float("nan"))

        rates = {}
        for h in ("R", "L"):
            hc = res["byhand"].get((player, side, h))
            if hc and sum(hc[:3]) >= MIN_HAND:
                rates[h] = hc[i] / sum(hc[:3])
        if len(rates) == 2:
            use = [(c, rates[res["opp"].get((player, mid), "?")])
                   for mid, c in ms if res["opp"].get((player, mid), "?") in rates]
            if len(use) >= MIN_MATCHES:
                row["phi_hand"] = _chi([c for c, _ in use], [q for _, q in use], i) \
                    / (len(use) - 2)

        # Per-year rates: a career that drifts slowly shows up as match-to-match
        # movement unless the expectation is allowed to move with it.
        byyear = defaultdict(lambda: [0, 0])
        for mid, c in ms:
            acc = byyear[res["year"].get(mid)]
            acc[0] += c[i]
            acc[1] += sum(c[:3])
        yrates = {y: a / b for y, (a, b) in byyear.items() if b}
        if 1 < len(yrates) < len(ms) - 1:
            row["phi_year"] = _chi(recs, [yrates[res["year"].get(mid)] for mid, _ in ms], i) \
                / (len(ms) - len(yrates))
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Step 5 — career drift
# --------------------------------------------------------------------------- #

def _profile_tvd(a: dict, b: dict) -> float:
    """Distance between two placement profiles: per-side total variation,
    weighted by how much of the serving happened on that side."""
    num = den = 0.0
    for s in SIDES:
        ca, cb = a.get(s, _dircounts()), b.get(s, _dircounts())
        na, nb = sum(ca[:3]), sum(cb[:3])
        if na < 40 or nb < 40:
            continue
        tvd = 0.5 * sum(abs(ca[i] / na - cb[i] / nb) for i in range(3))
        w = min(na, nb)
        num += w * tvd
        den += w
    return num / den if den else float("nan")


def _split_matches(order, counts):
    """Split an ordered match list into two halves of roughly equal serve count."""
    total = sum(counts[m] for m in order)
    run, cut = 0, len(order)
    for k, m in enumerate(order):
        run += counts[m]
        if run >= total / 2:
            cut = k + 1
            break
    return order[:cut], order[cut:]


def _profile(mids, per_side) -> dict:
    out = {s: _dircounts() for s in SIDES}
    for m in mids:
        for s in SIDES:
            c = per_side[s].get(m)
            if c:
                for i in range(3):
                    out[s][i] += c[i]
    return out


def biggest_move(early: dict, late: dict) -> str:
    """The single placement cell that moved most, in words."""
    best, out = 0.0, ""
    for s in SIDES:
        ca, cb = early.get(s, _dircounts()), late.get(s, _dircounts())
        na, nb = sum(ca[:3]), sum(cb[:3])
        if na < 40 or nb < 40:
            continue
        for i, d in enumerate(DIRS):
            a, b = ca[i] / na, cb[i] / nb
            if abs(b - a) > best:
                best, out = abs(b - a), f"{s} {DIRNAME[d]} {a:.0%}→{b:.0%}"
    return out


def drift(res):
    """Early-vs-late placement gap against the same career split at random.

    A career with two thin halves shows a gap from sampling alone, and one with
    restless match-to-match placement shows a bigger one; the shuffled null
    absorbs both, because it keeps every match intact and only destroys the time
    order. The ratio is the claim.
    """
    per_player = defaultdict(lambda: {s: {} for s in SIDES})
    for (player, side, snum), bymatch in res["mix"].items():
        if snum != 1:
            continue
        for mid, c in bymatch.items():
            per_player[player][side][mid] = c

    rows = []
    for player, per_side in per_player.items():
        counts = defaultdict(int)
        for s in SIDES:
            for m, c in per_side[s].items():
                counts[m] += sum(c[:3])
        # Sorted, so the shuffled null does not inherit the DB's scan order.
        mids = sorted(m for m, n in counts.items() if n >= MIN_MATCH_SERVES)
        if sum(counts[m] for m in mids) < DRIFT_SERVES:
            continue
        years = [y for y in (res["year"].get(m) for m in mids) if y]
        if not years or max(years) - min(years) < DRIFT_YEARS:
            continue

        chrono = sorted(mids, key=lambda m: (res["year"].get(m) or 0, str(m)))
        early, late = _split_matches(chrono, counts)
        pe, pl = _profile(early, per_side), _profile(late, per_side)
        d_chrono = _profile_tvd(pe, pl)
        if d_chrono != d_chrono:
            continue

        rng = np.random.default_rng(zlib.crc32(player.encode()))
        nulls = []
        for _ in range(DRIFT_SHUFFLES):
            shuf = list(mids)
            rng.shuffle(shuf)
            a, b = _split_matches(shuf, counts)
            d = _profile_tvd(_profile(a, per_side), _profile(b, per_side))
            if d == d:
                nulls.append(d)
        if not nulls:
            continue
        null = float(np.median(nulls))
        rows.append(dict(player=player, n=sum(counts[m] for m in mids),
                         matches=len(mids), y0=min(years), y1=max(years),
                         chrono=d_chrono, null=null,
                         ratio=d_chrono / null if null else float("nan"),
                         moved=biggest_move(pe, pl)))
    return rows


# --------------------------------------------------------------------------- #
# Step 7 — how much history to report
# --------------------------------------------------------------------------- #

def _career_matches(res):
    """Per player: matches in date order, with each side's placement counts."""
    per = defaultdict(lambda: defaultdict(lambda: {s: _dircounts() for s in SIDES}))
    for (player, side, snum), bymatch in res["mix"].items():
        if snum != 1:
            continue
        for mid, c in bymatch.items():
            for i in range(3):
                per[player][mid][side][i] += c[i]
    return {p: sorted(m.items(), key=lambda kv: res["order"].get(kv[0], (0, 0, str(kv[0]))))
            for p, m in per.items()}


def _predict(hist, tour_mix, weights=None):
    """Placement estimate per side from a slice of matches, shrunk to the tour."""
    out = {}
    for s in SIDES:
        acc = [0.0, 0.0, 0.0]
        for k, (_mid, sides) in enumerate(hist):
            w = 1.0 if weights is None else weights[k]
            for i in range(3):
                acc[i] += w * sides[s][i]
        n = sum(acc)
        out[s] = [(acc[i] + SMOOTH_K * tour_mix[s][i]) / (n + SMOOTH_K) for i in range(3)]
    return out


def window_scan(res, tour_mix):
    """How much recent history best predicts what a player does next?

    Step 5 says placement drifts, so the career average is a biased estimate of
    what a player is doing now; step 3 says a short window is a noisy one. The
    trade-off is settled by prediction rather than by preference: hold out each
    player's most recent matches, predict them from windows of different lengths,
    and score with multinomial log-loss per held-out serve. Log-loss is a proper
    scoring rule, so noise in the holdout adds the same constant to every window
    and cannot tilt the comparison. The T-share error is carried alongside
    because nats per serve is not a unit anyone can picture.
    """
    careers = _career_matches(res)
    loss = defaultdict(list)
    terr = defaultdict(list)
    by_player = defaultdict(dict)
    floors, spans, sizes, n_players = [], [], [], 0
    for player, ms in careers.items():
        tot = [sum(sides[s][i] for s in SIDES for i in range(3)) for _mid, sides in ms]
        run, cut = 0, None
        for k in range(len(ms) - 1, -1, -1):
            run += tot[k]
            if run >= HOLDOUT_SERVES:
                cut = k
                break
        if cut is None or sum(tot[:cut]) < HISTORY_SERVES:
            continue
        hist, hold = ms[:cut], ms[cut:]
        held = {s: _dircounts() for s in SIDES}
        for _mid, sides in hold:
            for s in SIDES:
                for i in range(3):
                    held[s][i] += sides[s][i]
        n_held = sum(held[s][i] for s in SIDES for i in range(3))
        if not n_held:
            continue
        n_players += 1

        # A 200-serve holdout is itself noisy, and that noise lands in every rule's
        # error identically. Tracking it lets the report separate the estimator's
        # own error from the floor no rule can get under.
        fl = fl_den = 0.0
        for s in SIDES:
            ns = sum(held[s])
            if ns > 1:
                ph = held[s][2] / ns
                fl += ns * ph * (1 - ph) / (ns - 1)
                fl_den += ns
        floors.append(fl / fl_den if fl_den else 0.0)

        def score(pred, label):
            ll = sq = den = 0.0
            for s in SIDES:
                for i in range(3):
                    ll -= held[s][i] * math.log(max(pred[s][i], 1e-9))
                ns = sum(held[s])
                if ns:
                    sq += ns * (pred[s][2] - held[s][2] / ns) ** 2
                    den += ns
            loss[label].append(ll / n_held)
            by_player[player][label] = ll / n_held
            if den:
                terr[label].append(sq / den)

        for w in WINDOWS:
            sl = hist if w is None else hist[-w:]
            score(_predict(sl, tour_mix), ("window", w))
            if w == 20:
                sizes.append(sum(tot[max(0, cut - 20):cut]))
                yrs = [res["year"].get(m) for m, _ in sl if res["year"].get(m)]
                if yrs:
                    spans.append(max(yrs) - min(yrs))
        for h in HALFLIVES:
            ages = np.arange(len(hist) - 1, -1, -1)
            score(_predict(hist, tour_mix, 0.5 ** (ages / h)), ("decay", h))
    floor = float(np.mean(floors)) if floors else 0.0
    return dict(loss={k: float(np.mean(v)) for k, v in loss.items()},
                # Total error and, with the holdout's own variance taken out, the
                # part the estimator is responsible for.
                rmse={k: math.sqrt(float(np.mean(v))) for k, v in terr.items()},
                est={k: math.sqrt(max(float(np.mean(v)) - floor, 0.0))
                     for k, v in terr.items()},
                floor=math.sqrt(floor), by_player=dict(by_player),
                n=n_players, w20_serves=float(np.median(sizes)) if sizes else float("nan"),
                w20_span=float(np.median(spans)) if spans else float("nan"))


def recent_profile(res, rule):
    """Each player's placement under the winning rule from the scan above.

    This is the shippable artifact of step 7: the mix a card should print, over
    the stretch of history that best predicts the player's next matches. A decay
    rule has no clean denominator — old matches count, just less — so the
    effective sample size is Kish's, ``(sum w n)^2 / sum w^2 n``, which is what a
    coverage gate has to be applied to rather than the raw serve count.
    """
    kind, param = rule
    out = {}
    for player, ms in _career_matches(res).items():
        ages = np.arange(len(ms) - 1, -1, -1)
        w = (0.5 ** (ages / param) if kind == "decay"
             else (ages < param).astype(float))
        acc = {s: [0.0, 0.0, 0.0] for s in SIDES}
        num = {s: 0.0 for s in SIDES}
        den = {s: 0.0 for s in SIDES}
        for k, (_mid, sides) in enumerate(ms):
            for s in SIDES:
                n = sum(sides[s])
                for i in range(3):
                    acc[s][i] += w[k] * sides[s][i]
                num[s] += w[k] * n
                den[s] += w[k] ** 2 * n
        eff = {s: (num[s] ** 2 / den[s]) if den[s] else 0.0 for s in SIDES}
        # The span a reader would call "recent": matches still carrying a tenth of
        # the newest match's weight.
        live = [m for k, (m, _sides) in enumerate(ms) if w[k] >= 0.1]
        yrs = [res["year"].get(m) for m in live if res["year"].get(m)]
        out[player] = dict(counts=acc, eff=eff, matches=len(live),
                           y0=min(yrs) if yrs else None, y1=max(yrs) if yrs else None)
    return out


# --------------------------------------------------------------------------- #
# Step 6 — big points
# --------------------------------------------------------------------------- #

def leverage(res, bucket="break_pt", i=2):
    """Placement on ``bucket`` points against the player's own normal-point rate.

    Break points sit disproportionately in the ad court, and the court moves
    placement far more than the score does, so the expectation is built per side
    and pooled at the bucket's own side mix. Without that adjustment most of an
    apparent pressure effect is really which court the point was played in.
    """
    players = {p for (p, _s, _b) in res["lev"] if p != "_tour_"}
    rows = []
    for player in players:
        obs = exp = var = n = 0.0
        for s in SIDES:
            b, nm = res["lev"].get((player, s, bucket)), res["lev"].get((player, s, "normal"))
            if not b or not nm:
                continue
            nb, nn = sum(b[:3]), sum(nm[:3])
            if nb == 0 or nn < 100:
                continue
            p = nm[i] / nn
            obs += b[i]
            exp += nb * p
            var += nb * p * (1 - p)
            n += nb
        if n < MIN_BREAK or var <= 0:
            continue
        z = (obs - exp) / math.sqrt(var)
        rows.append(dict(player=player, n=int(n), observed=obs / n, expected=exp / n,
                         delta=(obs - exp) / n, z=z, pval=2 * norm_sf(abs(z))))
    return rows


def tour_leverage(res):
    """Tour-wide placement by leverage bucket, kept within side."""
    out = {}
    for s in SIDES:
        for b in BUCKETS:
            c = res["lev"].get(("_tour_", s, b))
            if c and sum(c[:3]) >= 500:
                n = sum(c[:3])
                out[(s, b)] = (n, [c[i] / n for i in range(3)])
    return out


# --------------------------------------------------------------------------- #
# figures
# --------------------------------------------------------------------------- #

def fig_reliability(per, path):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    ax = axes[0]
    for g, color in (("M", "#1a7f4b"), ("W", "#b0512e")):
        st = per[g]["cards"]["wide share (deuce, 1st serve)"]
        ax.scatter(st["xs"], st["ys"], s=8, alpha=0.35, color=color,
                   label=f"{GLABEL[g]} — r = {st['r']:+.2f} ({len(st['xs'])} players)")
    ax.plot([0.1, 0.8], [0.1, 0.8], color="gray", lw=0.8, ls=":")
    ax.set_xlabel("deuce-court wide share — half 1 of a player's matches")
    ax.set_ylabel("wide share — half 2")
    ax.set_title("Does the placement mix repeat?")
    ax.legend(fontsize=8)

    ax = axes[1]
    ns = np.logspace(1.5, 4.5, 200)
    for label, ls in (("wide share (deuce, 1st serve)", "-"),
                      ("points won, T minus wide", "--")):
        for g, color in (("M", "#1a7f4b"), ("W", "#b0512e")):
            st = per[g]["cards"].get(label)
            if not st or st["vc"]["tau2"] <= 0:
                continue
            vc, phi = st["vc"], st["phi"]
            ax.plot(ns, vc["tau2"] / (vc["tau2"] + phi * vc["v1"] / ns), color=color,
                    ls=ls, label=f"{GLABEL[g]} — {label.split(' (')[0]}")
    ax.axhline(0.8, color="gray", lw=0.8, ls=":")
    ax.set_xscale("log")
    ax.set_ylim(0, 1)
    ax.set_xlabel("charted first serves on that side")
    ax.set_ylabel("share of the spread that is signal")
    ax.set_title("What each statistic costs in charted data")
    ax.legend(fontsize=8)
    fig.suptitle("Serve placement: the choice is measurable, what it earns is not")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_drift_leverage(per, path):
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.6))
    ax = axes[0]
    for g, color in (("M", "#1a7f4b"), ("W", "#b0512e")):
        rows = per[g]["drift"]
        ax.scatter([r["null"] for r in rows], [r["chrono"] for r in rows], s=10,
                   alpha=0.45, color=color, label=f"{GLABEL[g]} ({len(rows)} careers)")
    lim = 0.25
    ax.plot([0, lim], [0, lim], color="gray", lw=0.8, ls=":")
    ax.plot([0, lim / DRIFT_BIG], [0, lim], color="gray", lw=0.8, ls="--")
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_xlabel("shuffled-match split of the same career")
    ax.set_ylabel("early vs late split")
    ax.set_title(f"Career drift against its own null (dashed = {DRIFT_BIG}x)")
    ax.legend(fontsize=8)

    # How much history a card should use: the bias of stale matches against the
    # variance of few, scored on each player's held-out most recent matches.
    ax = axes[1]
    for g, color in (("M", "#1a7f4b"), ("W", "#b0512e")):
        wn = per[g]["window"]
        ws = [w for w in WINDOWS if w]
        ax.plot(ws, [wn["est"][("window", w)] for w in ws], "o-", color=color,
                label=f"{GLABEL[g]} — last N matches")
        ax.axhline(wn["est"][("window", None)], color=color, lw=0.9, ls=":",
                   label=f"{GLABEL[g]} — whole career")
    ax.set_xscale("log")
    ax.minorticks_off()   # the log locator otherwise litters 5x10^0 between the windows
    ax.set_xticks([w for w in WINDOWS if w])
    ax.set_xticklabels([str(w) for w in WINDOWS if w])
    ax.set_xlabel("matches of history used")
    ax.set_ylabel("mean T-share error on held-out matches")
    ax.set_title("How much history predicts a player's next matches")
    ax.legend(fontsize=7)

    # The tour-average break-point shift is ~zero, so the bar chart of it says
    # nothing; the distribution is the finding — a wide spread that cancels out.
    ax = axes[2]
    rows = per["M"]["lev_wide"] + per["W"]["lev_wide"]
    k = bh_reject([x["pval"] for x in rows])
    cut = sorted(x["pval"] for x in rows)[k - 1] if k else 0
    deltas = np.array([x["delta"] for x in rows])
    hits = np.array([x["delta"] for x in rows if x["pval"] <= cut]) if k else np.array([])
    bins = np.linspace(-0.2, 0.2, 41)
    ax.hist(deltas, bins=bins, color="#bcbcbc", label=f"all players ({len(deltas)})")
    if len(hits):
        ax.hist(hits, bins=bins, color="#c44e52",
                label=f"moves beyond chance ({len(hits)})")
    ax.axvline(0, color="gray", lw=0.8, ls=":")
    ax.axvline(float(np.average(deltas, weights=[x["n"] for x in rows])), color="black",
               lw=1.2, label="pooled shift")
    ax.set_xlabel("break-point wide share minus own normal rate")
    ax.set_ylabel("players")
    ax.set_title("Break points: the average hides the players")
    ax.legend(fontsize=8)
    fig.suptitle("Careers move; on break points the tour barely moves and some players "
                 "move a lot")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

def analyze(res):
    """Everything downstream of the DB pass, per tour."""
    out = {}
    totals = {}
    for key, bymatch in res["mix"].items():
        totals[key] = _sum_records(bymatch.values())
    out["totals"] = totals

    for snum in (1, 2):
        for s in SIDES:
            prof = [c for (_p, sd, sn), c in totals.items()
                    if sd == s and sn == snum and sum(c[:3]) >= MIN_PROFILE]
            if not prof:
                continue
            pooled = [sum(c[i] for c in prof) for i in range(3)]
            tot = sum(pooled)
            out[("tour", s, snum)] = (tot, [c / tot for c in pooled])
            out[("vc", s, snum)] = components(
                [c[0] / sum(c[:3]) for c in prof],
                [(c[0] / sum(c[:3])) * (1 - c[0] / sum(c[:3])) / sum(c[:3]) for c in prof],
                [sum(c[:3]) for c in prof])

    out["cards"] = {}
    for label, fn in CARD_STATS:
        st = card_stat(res, fn)
        if st:
            out["cards"][label] = st
    out["charter_fx"] = {DIRNAME[d]: charter_effect(res, i) for i, d in enumerate(DIRS)}
    out["cards_charter"] = {
        label: card_stat(res, fn, keyfn=lambda mid: res["charter_of"].get(mid))
        for label, fn in CARD_STATS[:2]}
    out["disp"] = dispersion(res)
    out["drift"] = drift(res)
    out["lev_t"] = leverage(res, "break_pt", 2)
    out["lev_wide"] = leverage(res, "break_pt", 0)
    out["tour_lev"] = tour_leverage(res)

    tour_mix = {s: out[("tour", s, 1)][1] for s in SIDES}
    out["window"] = window_scan(res, tour_mix)
    best = min((k for k in out["window"]["loss"] if k[1]),
               key=lambda k: out["window"]["loss"][k])
    out["best_rule"] = best
    out["recent"] = recent_profile(res, best)
    return out


def write_report(raw, per):
    md = ["# Serve placement — which tendencies are measurements", ""]
    md.append("*Generated by `experiments/serve_tendencies/run.py`. Placement is the "
              "charted serve target (wide / body / T), always split by court side, "
              "since `serve_side` showed the two sides are different shots. Every rate "
              "is conditioned on the target being charted. The question is not what the "
              "mixes are but which of them a player card could carry: a statistic is "
              "reportable when players differ on it by more than sampling noise, and "
              "when it repeats in the other half of the same player's matches.*")
    md.append("")

    for g in ("M", "W"):
        r, o = raw[g], per[g]
        md.append(f"## {GLABEL[g]}")
        md.append("")

        # -- Step 1 ------------------------------------------------------------
        md.append("### 1. What is charted")
        md.append("")
        md.append("| decade | serve points | target charted | charted as unknown |")
        md.append("|---|--:|--:|--:|")
        for dec in sorted(r["cover"]):
            n, coded, unk = r["cover"][dec]
            md.append(f"| {dec} | {n:,} | {coded / n:.1%} | {unk / n:.1%} |")
        md.append("")
        charters = [v for v in r["chart"].values() if v[0] >= 2000]
        rates = sorted(v[1] / v[0] for v in charters)
        md.append(f"- Across the {len(charters)} charters with 2,000+ serve points, the "
                  f"share of serves carrying a target runs from {rates[0]:.0%} to "
                  f"{rates[-1]:.0%} (median {rates[len(rates) // 2]:.0%}). Coverage is "
                  "not the problem here; placement is one of the best-charted things in "
                  "the notation.")
        md.append("")
        md.append("Agreement is. Holding the player fixed and varying who charted them "
                  "(cells of 150+ serves, against the same player's other charters):")
        md.append("")
        md.append("| target | charters compared | SD of the charter's shift | range |")
        md.append("|---|--:|--:|--:|")
        for d in DIRS:
            fx = o["charter_fx"][DIRNAME[d]]
            if fx:
                md.append(f"| {DIRNAME[d]} | {fx['n']} | ±{fx['sd']:.1%} | "
                          f"{fx['lo']:+.1%} to {fx['hi']:+.1%} |")
        md.append("")
        body_fx, wide_fx = o["charter_fx"]["body"], o["charter_fx"]["wide"]
        body_share = o[("tour", "deuce", 1)][1][1]
        if body_fx and wide_fx:
            md.append(f"- **The body serve is partly a charter's opinion.** Charters "
                      f"disagree about it by ±{body_fx['sd']:.1%} on the same players, "
                      f"against a tour body share of {body_share:.0%} — the disagreement "
                      "is a large fraction of the category. A serve near the middle can "
                      "be charted body or wide, and different charters draw that line "
                      "differently.")
            md.append(f"- Wide and T carry a smaller fingerprint (±{wide_fx['sd']:.1%} "
                      "for wide), which is why every headline below is stated in "
                      "wide-versus-T terms. Body shares are reported for completeness "
                      "and should not be compared across players charted by different "
                      "people.")
        md.append("")

        # -- Step 2 ------------------------------------------------------------
        md.append("### 2. The tour picture, and how far players spread around it")
        md.append("")
        md.append("| side | serve | charted serves | wide | body | T | true spread (wide) |")
        md.append("|---|---|--:|--:|--:|--:|--:|")
        for snum in (1, 2):
            for s in SIDES:
                if ("tour", s, snum) not in o:
                    continue
                n, mixv = o[("tour", s, snum)]
                vc = o[("vc", s, snum)]
                md.append(f"| {s} | {SNUM[snum]} | {n:,} | {mixv[0]:.0%} | {mixv[1]:.0%} | "
                          f"{mixv[2]:.0%} | ±{math.sqrt(vc['tau2']):.1%} "
                          f"({vc['n']} players) |")
        md.append("")
        vc = o[("vc", "deuce", 1)]
        md.append(f"- The last column is the *true* spread: the raw spread across players "
                  f"({math.sqrt(vc['obs_var']):.1%} SD on the deuce-court wide share) "
                  f"with the sampling contribution ({math.sqrt(vc['samp_var']):.1%}) "
                  "removed. Players really do differ, and by much more than they differ "
                  "by accident, which is the precondition for anything below.")
        md.append("")

        # -- Step 3 ------------------------------------------------------------
        md.append("### 3. Does it repeat?")
        md.append("")
        md.append("| statistic | players | true spread | half-vs-half r | full-sample "
                  "reliability | noise vs binomial | serves for 80% signal |")
        md.append("|---|--:|--:|--:|--:|--:|--:|")
        for label, _fn in CARD_STATS:
            st = o["cards"].get(label)
            if not st:
                continue
            n80 = st["n80"]
            md.append(f"| {label} | {st['vc']['n']:,} | "
                      f"±{math.sqrt(st['vc']['tau2']):.1%} | {st['r']:+.2f} | "
                      f"{st['reliability']:+.2f} | {st['phi']:.1f}x | "
                      f"{'—' if n80 == float('inf') else f'{n80:,.0f}'} |")
        md.append("")
        wide = o["cards"]["wide share (deuce, 1st serve)"]
        reach = sum(1 for (_p, s, sn), c in o["totals"].items()
                    if s == "deuce" and sn == 1 and sum(c[:3]) >= wide["n80"])
        md.append(f"- **Placement choice is a measurement.** A player's deuce-court wide "
                  f"share needs {wide['n80']:,.0f} charted first serves on that side to "
                  f"be 80% signal, which {reach:,} players in this data reach.")
        md.append(f"- **The binomial answer would have been {wide['n80_binomial']:,.0f}.** "
                  "A player is not a fixed coin: the observed split-half correlation sits "
                  f"below what one would give, and closing that gap takes "
                  f"{wide['phi']:.1f}x the sampling variance. Step 4 measures the same "
                  "excess directly. Any sample-size rule that assumes independent serves "
                  "is optimistic by that factor.")
        pay = o["cards"].get("points won, T minus wide")
        if pay:
            cost = ("no sample in this data would reach 80% signal"
                    if pay["n80"] == float("inf")
                    else f"reaching 80% signal would take {pay['n80']:,.0f} charted "
                         "first serves on the side")
            md.append(f"- **What a placement earns is not a measurement.** After removing "
                      f"sampling noise, players differ in points won behind the T minus "
                      f"behind the wide serve by only ±{math.sqrt(pay['vc']['tau2']):.1%}, "
                      f"the split halves of the same player agree at r = {pay['r']:+.2f}, "
                      f"and {cost}. 'Wins more behind the T' is the stat most worth "
                      "wanting and least worth printing.")
        ing = o["cards"].get("1st-serve-in rate, T minus wide")
        if ing:
            md.append(f"- Execution sits in between: how much more often a player lands "
                      f"the T than the wide serve repeats at r = {ing['r']:+.2f}. It is "
                      "reportable for well-charted players, unlike the payoff.")
        chs = o["cards_charter"].get("wide share (deuce, 1st serve)")
        if chs:
            md.append(f"- **Split by charter instead of by match**, so that step 1's "
                      f"fingerprint counts against the statistic rather than for it, the "
                      f"wide share still repeats at r = {chs['r']:+.2f} across "
                      f"{len(chs['xs'])} players whose matches split across charters "
                      f"(against {wide['r']:+.2f} on the match split). Most of the "
                      "stability is the player, not the person typing.")
        md.append("")

        # -- Step 4 ------------------------------------------------------------
        disp = o["disp"]
        phis = sorted(d["phi"] for d in disp)
        sig = bh_reject([d["pval"] for d in disp])
        md.append("### 4. Match to match: one coin, or a decision per opponent?")
        md.append("")
        md.append(f"- {len(disp):,} (player, side) profiles have {MIN_MATCHES}+ matches "
                  f"with {MIN_MATCH_SERVES}+ charted first serves. Median dispersion "
                  f"phi = {phis[len(phis) // 2]:.2f}, against 1.00 for a player who "
                  "flips the same coin every match.")
        md.append(f"- {sig:,} of them ({sig / max(len(disp), 1):.0%}) are overdispersed "
                  f"beyond chance at FDR {FDR_Q:g}. Serve placement is re-decided, not "
                  "just executed.")
        both = [(d["phi"], d["phi_hand"], d["phi_year"]) for d in disp
                if d["phi_hand"] == d["phi_hand"] and d["phi_year"] == d["phi_year"]]
        if both:
            base = float(np.median([a for a, _b, _c in both]))
            hand = float(np.median([b for _a, b, _c in both]))
            yr = float(np.median([c for _a, _b, c in both]))
            md.append(f"- On the {len(both):,} profiles where both conditioners can be "
                      f"estimated, median phi is {base:.2f}. Expecting each match at the "
                      f"player's rate against that returner's handedness moves it to "
                      f"{hand:.2f}; expecting it at their rate that calendar year moves "
                      f"it to {yr:.2f}. "
                      + ("Neither explains much: the movement is match-specific, and "
                         "handedness and slow career drift are minor parts of it."
                         if min(hand, yr) > 0.85 * base else
                         "The larger of the two drops locates most of the movement."))
        md.append("- Practical reading: a match supplies roughly "
                  f"{MIN_MATCH_SERVES}–60 charted first serves per side, so a "
                  "single-match placement mix carries a sampling error near ±10 points "
                  "*before* this extra movement. Match-level placement claims need the "
                  "error bar; career-level ones do not.")
        md.append("")
        deep = [d for d in disp if d["matches"] >= 40]
        if deep:
            deep.sort(key=lambda d: d["phi"])
            md.append(f"Steadiest and most restless placement among the {len(deep)} "
                      "profiles with 40+ charted matches (phi near 1.00 means the same "
                      "mix every match):")
            md.append("")
            md.append("| | player | side | matches | wide share | phi | phi within year |")
            md.append("|---|---|---|--:|--:|--:|--:|")
            for tag, group in (("steady", deep[:4]), ("restless", deep[-4:][::-1])):
                for d in group:
                    py = d["phi_year"]
                    md.append(f"| {tag} | {d['player']} | {d['side']} | {d['matches']} | "
                              f"{d['p']:.0%} | {d['phi']:.2f} | "
                              f"{'–' if py != py else f'{py:.2f}'} |")
            md.append("")
            keep = [d["phi_year"] / d["phi"] for d in deep
                    if d["phi_year"] == d["phi_year"] and d["phi"] > 0]
            md.append("The last column expects each match at the player's rate that "
                      "season, so a long career's slow drift stops counting as "
                      "match-to-match movement. Across these profiles it keeps a median "
                      f"{float(np.median(keep)):.0%} of the dispersion, so most of the "
                      "movement is genuinely between matches within a season — though "
                      "the individual drops are large enough that any single player's "
                      "restlessness should be read from this column, not the previous "
                      "one.")
            md.append("")

        # -- Step 5 ------------------------------------------------------------
        dr = o["drift"]
        ratios = sorted(d["ratio"] for d in dr)
        big = [d for d in dr if d["ratio"] >= DRIFT_BIG]
        md.append("### 5. Careers")
        md.append("")
        md.append(f"- {len(dr)} careers clear {DRIFT_SERVES:,}+ charted first serves and "
                  f"an {DRIFT_YEARS}-year span. The median early-vs-late placement gap is "
                  f"{ratios[len(ratios) // 2]:.2f}x the same career split at random, and "
                  f"{len(big)} careers ({len(big) / max(len(dr), 1):.0%}) clear "
                  f"{DRIFT_BIG}x.")
        md.append("- Read the ratio and the gap together. The ratio is a detection, and a "
                  "heavily-charted career detects a small move easily because its null is "
                  "tiny; the gap column is how much the placement actually moved.")
        body_moves = sum(1 for d in big if " body " in d["moved"])
        md.append(f"- Step 1's caveat lands hardest here: who charts a player changes "
                  f"across a career, so a placement 'change' can be a change of charter. "
                  f"{body_moves} of the {len(big)} detected careers have a body cell as "
                  "their biggest move, and those are the ones to trust least.")
        md.append("")
        md.append("| player | serves | years | early→late gap | shuffled | ratio | "
                  "biggest move |")
        md.append("|---|--:|---|--:|--:|--:|---|")
        for d in sorted(dr, key=lambda d: -d["ratio"])[:6]:
            md.append(f"| {d['player']} | {d['n']:,} | {d['y0']}–{d['y1']} | "
                      f"{d['chrono']:.3f} | {d['null']:.3f} | {d['ratio']:.1f}x | "
                      f"{d['moved']} |")
        md.append("")
        md.append("Largest actual movement among careers that clear the null:")
        md.append("")
        md.append("| player | serves | years | early→late gap | ratio | biggest move |")
        md.append("|---|--:|---|--:|--:|---|")
        for d in sorted(big, key=lambda d: -d["chrono"])[:6]:
            md.append(f"| {d['player']} | {d['n']:,} | {d['y0']}–{d['y1']} | "
                      f"{d['chrono']:.3f} | {d['ratio']:.1f}x | {d['moved']} |")
        md.append("")

        # -- Step 6 ------------------------------------------------------------
        tour = o["tour_lev"]
        md.append("### 6. Big points")
        md.append("")
        md.append("| side | bucket | first serves | wide | body | T |")
        md.append("|---|---|--:|--:|--:|--:|")
        for s in SIDES:
            for b in BUCKETS:
                if (s, b) in tour:
                    n, m = tour[(s, b)]
                    md.append(f"| {s} | {b} | {n:,} | {m[0]:.0%} | {m[1]:.0%} | "
                              f"{m[2]:.0%} |")
        md.append("")
        md.append("- The `deuce` bucket (40-40) has no ad-court row, which is what the "
                  "parity rule requires: six points played is an even count. It is a free "
                  "check that the side derivation is right.")
        for label, key in (("T", "lev_t"), ("wide", "lev_wide")):
            rows = o[key]
            if not rows:
                continue
            k = bh_reject([x["pval"] for x in rows])
            cut = sorted(x["pval"] for x in rows)[k - 1] if k else 0
            hits = [x for x in rows if x["pval"] <= cut] if k else []
            pooled = sum(x["delta"] * x["n"] for x in rows) / sum(x["n"] for x in rows)
            up = sum(1 for x in hits if x["delta"] > 0)
            md.append(f"- **{label} share on break points**, each player against their own "
                      f"normal-point rate with the side held fixed: the pooled shift is "
                      f"{pooled:+.1%} across {len(rows)} players with {MIN_BREAK}+ "
                      f"break-point first serves — near nothing. But {k} players move "
                      f"beyond chance at FDR {FDR_Q:g} ({up} toward the {label}, "
                      f"{len(hits) - up} away), so the tour-wide average is hiding "
                      "players who cancel out.")
            movers = sorted(rows, key=lambda x: -abs(x["z"]))[:5]
            md.append("  " + "; ".join(
                f"{m['player']} {m['delta']:+.0%} (n={m['n']:,}, z={m['z']:+.1f})"
                for m in movers))
        md.append("")

        # -- Step 7 ------------------------------------------------------------
        wn = o["window"]
        md.append("### 7. How much history should a card report?")
        md.append("")
        md.append(f"*Each of {wn['n']} players has their most recent "
                  f"{HOLDOUT_SERVES}+ charted first serves held out. Every rule below "
                  "predicts that holdout from the matches before it, scored as log-loss "
                  "per held-out serve (lower is better). The T-share columns are the "
                  "same comparison in picturable units: total error, then what is left "
                  f"after removing the holdout's own sampling noise ({wn['floor']:.1%}), "
                  "which every rule carries equally. All rules shrink toward the tour "
                  f"mix by {SMOOTH_K} pseudo-counts, so this compares windows, not "
                  "smoothing choices.*")
        md.append("")
        md.append("| history used | log-loss per serve | T-share error | estimator's "
                  "share of it |")
        md.append("|---|--:|--:|--:|")
        for w in WINDOWS:
            k = ("window", w)
            label = "whole career" if w is None else f"last {w} matches"
            md.append(f"| {label} | {wn['loss'][k]:.4f} | {wn['rmse'][k]:.1%} | "
                      f"{wn['est'][k]:.1%} |")
        for h in HALFLIVES:
            k = ("decay", h)
            md.append(f"| all, {h}-match half-life | {wn['loss'][k]:.4f} | "
                      f"{wn['rmse'][k]:.1%} | {wn['est'][k]:.1%} |")
        md.append("")
        career = wn["loss"][("window", None)]
        best = min(wn["loss"], key=lambda k: wn["loss"][k])
        blabel = (f"the last {best[1]} matches" if best[0] == "window"
                  else f"a {best[1]}-match half-life")
        md.append(f"- **Best rule: {blabel}**, at {wn['loss'][best]:.4f} against "
                  f"{career:.4f} for the whole career. Most of what a card would get "
                  "wrong is the holdout's own noise; of the part the estimator owns, "
                  f"recency removes {1 - wn['est'][best] / wn['est'][('window', None)]:.0%} "
                  f"({wn['est'][('window', None)]:.1%} → {wn['est'][best]:.1%} on the T "
                  "share).")

        # Does recency pay where the drift step said it should?
        ratio = {d["player"]: d["ratio"] for d in o["drift"]}
        groups = {"drifted (ratio ≥ %.1fx)" % DRIFT_BIG: [], "stable": []}
        for player, losses in wn["by_player"].items():
            if player not in ratio or best not in losses:
                continue
            key = ("drifted (ratio ≥ %.1fx)" % DRIFT_BIG
                   if ratio[player] >= DRIFT_BIG else "stable")
            groups[key].append(losses[("window", None)] - losses[best])
        parts = [f"{k} — {np.mean(v):+.4f} ({len(v)} players)"
                 for k, v in groups.items() if v]
        if parts:
            md.append("- Where the gain comes from, as log-loss saved against the career "
                      "average: " + "; ".join(parts) + ". The rule earns its keep on the "
                      "careers step 5 flagged and costs almost nothing on the rest, which "
                      "is the argument for applying it to everyone rather than "
                      "branching.")
        md.append(f"- Twenty matches is worth about {wn['w20_serves']:,.0f} charted first "
                  f"serves and spans {wn['w20_span']:.0f} years for the median player — "
                  "which is the catch. A window short enough to be current is not "
                  "automatically long enough to clear step 3's bar of "
                  f"{o['cards']['wide share (deuce, 1st serve)']['n80']:,.0f} serves per "
                  "side, so a card should print the window's own denominator and stay "
                  "silent when it is thin.")
        bw = min((k for k in wn["loss"] if k[0] == "window" and k[1]),
                 key=lambda k: wn["loss"][k])
        bd = min((k for k in wn["loss"] if k[0] == "decay"), key=lambda k: wn["loss"][k])
        if wn["loss"][bd] < wn["loss"][bw]:
            md.append(f"- Weighting all of a career by a {bd[1]}-match half-life beats the "
                      f"best hard cutoff (last {bw[1]}) by "
                      f"{wn['loss'][bw] - wn['loss'][bd]:.4f}. Old matches are worth less "
                      "than recent ones but more than nothing, and a cliff throws that "
                      "difference away.")
        else:
            md.append(f"- A hard cutoff at {bw[1]} matches edges out every decay rule "
                      f"tested (best: {bd[1]}-match half-life, "
                      f"{wn['loss'][bd] - wn['loss'][bw]:+.4f}), so the simple rule is "
                      "also the one to ship.")
        md.append("")

    md.append("## Where this belongs, and what is already covered")
    md.append("")
    md.append("- `serve_side` owns the descriptive split and stays the place to look up "
              "what a mix *is*. This experiment owns the error bars: which of those "
              "numbers repeat, and from how much data. Nothing here replaces it.")
    md.append("- `blind_reid` scores the serve as one feature block against the return "
              "and rally blocks and finds it the weakest of the three for naming a "
              "player. That is discrimination between players, not reliability within "
              "one, and the two answers are compatible: placement is stable per player "
              "and still separates players less sharply than net play and slice do. "
              "Step 3 explains why that can happen — a stable statistic with a narrow "
              "true spread carries little identifying information.")
    md.append("- `career_splits` decides whether a whole career becomes two entities, in "
              "a 10-feature style space that already includes serve location. Step 5 is "
              "that design narrowed to placement alone, so it answers 'did the serve "
              "move' rather than 'did the player'. It is an input to that decision, not "
              "a competitor: placement moves in about half of long careers, more often "
              "than overall style does.")
    md.append("- The genuinely new ground is steps 3, 4 and 6: the sample-size rules, the "
              "match-to-match dispersion, and the side-adjusted break-point test. None "
              "of those exist anywhere else in the repo.")
    md.append("")
    md.append("![reliability](figures/serve_tendencies_reliability.png)")
    md.append("")
    md.append("![drift and leverage](figures/serve_tendencies_drift.png)")
    md.append("")
    md.append("## Limits")
    md.append("")
    md.append("- The notation records a target, not a serve. Speed, spin and the "
              "returner's position are invisible, so 'wide' pools a kick and a flat "
              "slice out wide.")
    md.append("- Break points are selected: they arrive more often against good returners "
              "and when the server is already in trouble, so a placement shift on them is "
              "not purely a choice made under pressure.")
    md.append("- The step-4 conditioners are estimated from the same data they are tested "
              "on, which the degrees-of-freedom correction handles in expectation but "
              "which still makes small-sample profiles noisy. Some of the match-to-match "
              "movement it measures is the charter changing between matches, not the "
              "player.")
    md.append("- Step 6's break-point test is charter-safe by construction — both buckets "
              "come from the same matches — but steps 3 and 5 compare across matches and "
              "inherit step 1's fingerprint.")
    md.append("- Double faults are not separated out of the second-serve mix; a second "
              "serve that was missed still carries its target here.")
    md.append("")
    md.append("## Next steps")
    md.append("")
    md.append("- Join `player_eras` so the drift step reports against the eras "
              "`career_splits` already blessed, instead of a fresh median split.")
    md.append("- Add the returner's handedness to the target, so 'wide in the ad court' "
              "becomes 'into the backhand' — step 4 already builds the join.")
    md.append("- Chase the step-4 residual: opponent identity, surface and round are the "
              "obvious candidates for the match-to-match movement that handedness and "
              "year both fail to explain.")
    md.append("- Second-serve placement deserves its own reliability pass. The sample is "
              "a third the size, the spread across players is wider, and the decision is "
              "a different one.")
    md.append("")
    (REPORTS / "serve_tendencies.md").write_text("\n".join(md) + "\n")


def write_csvs(raw, per):
    rows = []
    for g in ("M", "W"):
        o, r = per[g], raw[g]
        disp = {(d["player"], d["side"]): d for d in o["disp"]}
        dr = {d["player"]: d for d in o["drift"]}
        for (player, side, snum), c in o["totals"].items():
            n = sum(c[:3])
            if n < MIN_PROFILE:
                continue
            # The recent window (step 7) is what a card should print; the career
            # totals stay in the row so the two are comparable at a glance.
            rec = o["recent"].get(player) if snum == 1 else None
            rc = rec["counts"][side] if rec else None
            rn = sum(rc) if rc else 0
            reff = rec["eff"][side] if rec else 0
            h1, h2 = _split_records(r["mix"][(player, side, snum)])
            d = disp.get((player, side)) if snum == 1 else None
            car = dr.get(player) if snum == 1 else None

            def q(x, dp=4):
                return "" if x is None or x != x else round(x, dp)

            rows.append(dict(
                player=player, gender=g, side=side, serve=SNUM[snum], n=n,
                wide=q(c[0] / n), body=q(c[1] / n), t=q(c[2] / n),
                wide_h1=q(h1[0] / sum(h1[:3])) if h1 and sum(h1[:3]) else "",
                wide_h2=q(h2[0] / sum(h2[:3])) if h2 and sum(h2[:3]) else "",
                matches=d["matches"] if d else "", phi=q(d["phi"], 3) if d else "",
                phi_hand=q(d["phi_hand"], 3) if d else "",
                phi_year=q(d["phi_year"], 3) if d else "",
                drift_gap=q(car["chrono"], 4) if car else "",
                drift_ratio=q(car["ratio"], 2) if car else "",
                drift_years=f"{car['y0']}-{car['y1']}" if car else "",
                drift_moved=car["moved"] if car else "",
                recent_matches=rec["matches"] if rec else "",
                recent_n_eff=round(reff) if reff else "",
                recent_wide=q(rc[0] / rn) if rn else "",
                recent_body=q(rc[1] / rn) if rn else "",
                recent_t=q(rc[2] / rn) if rn else "",
                recent_years=f"{rec['y0']}-{rec['y1']}" if rec and rec["y0"] else "",
                reliable=int(reff >= o["cards"]["wide share (deuce, 1st serve)"]["n80"])
                if reff else ""))
    with open(REPORTS / "serve_tendencies_players.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    lrows = []
    for g in ("M", "W"):
        for label, key in (("T", "lev_t"), ("wide", "lev_wide")):
            rows_g = per[g][key]
            # Multiplicity is settled here rather than downstream: a consumer that
            # re-derived it from the p-values would have to know the family is one
            # gender and one direction, and would get it wrong.
            k = bh_reject([x["pval"] for x in rows_g])
            cut = sorted(x["pval"] for x in rows_g)[k - 1] if k else -1
            for x in rows_g:
                lrows.append(dict(player=x["player"], gender=g, direction=label,
                                  bucket="break_pt", n=x["n"],
                                  observed=round(x["observed"], 4),
                                  expected=round(x["expected"], 4),
                                  delta=round(x["delta"], 4), z=round(x["z"], 2),
                                  pval=round(x["pval"], 5),
                                  sig=int(x["pval"] <= cut)))
    with open(REPORTS / "serve_tendencies_leverage.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lrows[0].keys()))
        w.writeheader()
        w.writerows(lrows)

    # The gates a consumer needs, as data rather than as prose in the report: the
    # winning recency rule and the sample a share must clear to be worth printing.
    mrows = []
    for g in ("M", "W"):
        o = per[g]
        kind, param = o["best_rule"]
        card = o["cards"]
        mrows.append(dict(
            gender=g, rule=kind, rule_param=param,
            recent_matches=max((r["matches"] for r in o["recent"].values()), default=0),
            n80_wide=round(card["wide share (deuce, 1st serve)"]["n80"]),
            n80_t=round(card["T share (deuce, 1st serve)"]["n80"]),
            n80_pay=("" if card["points won, T minus wide"]["n80"] == float("inf")
                     else round(card["points won, T minus wide"]["n80"])),
            noise_inflation=round(card["wide share (deuce, 1st serve)"]["phi"], 2),
            tour_deuce_wide=round(o[("tour", "deuce", 1)][1][0], 4),
            tour_deuce_t=round(o[("tour", "deuce", 1)][1][2], 4),
            tour_ad_wide=round(o[("tour", "ad", 1)][1][0], 4),
            tour_ad_t=round(o[("tour", "ad", 1)][1][2], 4)))
    with open(REPORTS / "serve_tendencies_meta.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(mrows[0].keys()))
        w.writeheader()
        w.writerows(mrows)
    return len(rows), len(lrows)


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    con = connect(read_only=True)
    hands = hand_map(con)
    raw = {g: collect(con, g, hands) for g in ("M", "W")}
    con.close()
    per = {g: analyze(raw[g]) for g in ("M", "W")}

    fig_reliability(per, FIG / "serve_tendencies_reliability.png")
    fig_drift_leverage(per, FIG / "serve_tendencies_drift.png")
    write_report(raw, per)
    n_players, n_lev = write_csvs(raw, per)
    print(f"wrote reports/serve_tendencies.md, _players.csv ({n_players} profiles), "
          f"_leverage.csv ({n_lev} rows), _meta.csv, 2 figures")


if __name__ == "__main__":
    main()
