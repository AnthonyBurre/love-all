"""Build the compact ``insights.duckdb`` the Pages site queries in-browser via DuckDB-WASM.

A small projection of the main DB — one row per charted player — assembled from the
experiment CSVs + the graduated library, keyed by **base player name** (era-split
entities are collapsed to their most recent era = current form). Aggregates only, so it
stays small enough to ship; nothing is committed (it lands under gitignored ``data/``).

Prereq: the experiments have been run so their CSVs exist in ``reports/`` (the CI
insights workflow runs them first). Run: ``match-charting-project site build-insights``.
"""

import math
import re
from collections import defaultdict
from datetime import date

import duckdb
import pandas as pd

from match_charting_project.live.players import (
    coverage,
    coverage_by_match,
    coverage_by_year,
    normalize,
    tourn_key,
)
from match_charting_project.paths import DATA_DIR, DB_PATH, PROJECT_ROOT
from match_charting_project.shots.notation import (
    MIX_FIELDS,
    blank_mix,
    fold_shot_mix,
    parse_point,
)
from match_charting_project.winprob_match import current_strength

REPORTS = PROJECT_ROOT / "reports"
# The shot-mix rate columns, in the order the panel prints them. ``_shot_mix`` returns exactly
# these.
MIX_RATES = ("fh_share", "fh_winner_pct", "fh_err_pct",
             "bh_share", "bh_winner_pct", "bh_err_pct",
             "slice_pct",
             "net_pct", "net_winner_pct", "net_err_pct")
# The stroke counts they are over.
MIX_COUNTS = ("gs", "fh_gs", "bh_gs", "rally_shots", "net_shots")
# The denominators the panel reads beside the rates, for its test of whether two players'
# rates really differ. The rest of the counts the floors are applied on are dropped.
SHIPPED_COUNTS = ("serve_pts", "second_pts", "serve_games", "return_games", "ret_pts",
                  "fh_gs", "bh_gs", "net_shots")
OUT = DATA_DIR / "insights.duckdb"
_ERA_RE = re.compile(r"^(?P<base>.+) \((?P<y0>\d{4})[–-](?P<y1>\d{4})\)$")
# Only recent slam/1000 identities ship: completed events are archived going forward, so
# older per-match charting status is never needed.
_CHARTED_SINCE = date.today().year - 2


def _base(entity: str) -> "tuple[str, int]":
    m = _ERA_RE.match(str(entity))
    return (m["base"], int(m["y1"])) if m else (str(entity), 0)


def _collapse(df: pd.DataFrame, mean_over: "dict | None" = None) -> pd.DataFrame:
    """Collapse era entities to base names, keeping the latest era per (gender, player).

    Latest-era suits the archetype and its confidence flag. ``mean_over`` names measurements
    to average across eras instead, weighted by the named column, so the figure covers the
    same matches as the coverage band beside it (Connors' two eras run 4.90 and 6.16 shots).
    """
    df = df.copy()
    parsed = [_base(p) for p in df["player"]]
    df["player"] = [b for b, _ in parsed]
    df["_y1"] = [y for _, y in parsed]
    latest = df.sort_values("_y1").groupby(["gender", "player"], as_index=False).last()
    if mean_over:
        for col, weight in mean_over.items():
            w = df[weight].fillna(0.0)
            wsum = w.groupby([df.gender, df.player]).transform("sum")
            # An all-zero-weight player would divide by zero; they keep the latest era,
            # which is what the unweighted path would have given them anyway.
            share = (w / wsum).where(wsum > 0, 0.0)
            avg = (df[col] * share).groupby([df.gender, df.player]).sum()
            avg = avg.where(wsum.groupby([df.gender, df.player]).first() > 0)
            latest[col] = latest.set_index(["gender", "player"]).index.map(avg)
    return latest.drop(columns="_y1")


def _charted_matches(con) -> pd.DataFrame:
    """Recent slam/1000 charted matches, keyed so the fast path can flag per-match charting.

    Names/tournaments are normalized here (via the shared ``players`` helpers) so the join
    in ``build_brackets`` is a plain dict lookup — no fuzzy matching on the hot path.
    """
    rows = con.execute(
        "SELECT match_id, gender, year, tournament, player1, player2, charted_by "
        "FROM matches WHERE is_qualifying = false AND year >= ? "
        "AND tier IN ('Grand Slam', 'Masters / WTA 1000')",
        [_CHARTED_SINCE]).fetchall()
    df = pd.DataFrame(rows, columns=["match_id", "gender", "year", "tournament",
                                     "player1", "player2", "charted_by"])
    df["tourn_key"] = df["tournament"].map(tourn_key)
    df["p1_norm"] = df["player1"].map(normalize)
    df["p2_norm"] = df["player2"].map(normalize)
    return df[["gender", "year", "tourn_key", "p1_norm", "p2_norm", "match_id", "charted_by"]]


# --- when a career figure prints ---------------------------------------------------------
# Every rate on the panel says what happened across a player's charted matches, so it prints
# once it is precise: its 95% margin within ±10 points and within half the rate itself (half
# its complement, for a rate above 50%). The first clause bounds a middling rate; the second
# keeps a rare one from printing on a handful of events, and comes to about 15 of them. A 50%
# rate needs 97 of its denominator, a 10% rate 139, a 2% rate 753.
#
# The floor for each rate and tour comes from that tour's typical value of it, the median
# over established players (ESTABLISHED_PTS or more charted points), so it is set by the data
# rather than kept by hand. _apply_floors applies them all in one place and ships them in
# ``meta`` as ``floor_<rate>_<gender>`` for the panel's notes.
#
# Whether one player's rate beats another's is a separate question, answered on the panel by
# a two-proportion test before either is set in bold.
Z = 1.96
MARGIN = 0.10
ESTABLISHED_PTS = 2000

# Each rate and the count it is over. The serve plot's four rates print together or not at all
# (SERVE_PLOT), since a column without its fill reads as a rate of zero.
RATES = (
    ("hold_rate", "serve_games"), ("break_rate", "return_games"),
    ("first_in_pct", "serve_pts"), ("second_in_pct", "second_pts"),
    ("first_won_pct", "first_in_n"), ("second_won_pct", "second_pts"),
    ("ace_rate", "serve_pts"), ("first_ace_pct", "first_n"), ("second_ace_pct", "second_n"),
    ("ret_winner_rate", "ret_pts"),
    ("fh_share", "gs"), ("bh_share", "gs"),
    ("fh_winner_pct", "fh_gs"), ("fh_err_pct", "fh_gs"),
    ("bh_winner_pct", "bh_gs"), ("bh_err_pct", "bh_gs"),
    ("slice_pct", "rally_shots"), ("net_pct", "rally_shots"),
    ("net_winner_pct", "net_shots"), ("net_err_pct", "net_shots"),
)
SERVE_PLOT = ("first_in_pct", "second_in_pct", "first_won_pct", "second_won_pct")

# The two figures that are not rates. Average winning rally length is a mean: at 200 won points
# its margin is about ±0.45 shots (SD ≈ 3.3), a tenth of the typical value. Variety is a mean
# surprise in bits, and one match's worth of strokes already gives a split-half reliability of
# 0.59 (men) / 0.64 (women).
WON_LEN_POINTS = 200
VARIETY_STROKES = 300


def precision_floor(p: float) -> float:
    """The smallest denominator at which a rate near ``p`` is precise enough to print."""
    q = min(p, 1 - p)
    if not q > 0:
        return math.inf
    tol = min(MARGIN, q / 2)
    return math.ceil(Z * Z * p * (1 - p) / (tol * tol))


def _apply_floors(summary: pd.DataFrame) -> "tuple[pd.DataFrame, list]":
    """Withhold every rate under its floor, and return the floors as ``meta`` rows.

    ``summary`` carries the raw rates, their denominators (RATES) and ``points_charted``.
    """
    df = summary.copy()
    rows = []
    for g in sorted(df.gender.dropna().unique()):
        tour = df.gender == g
        est = tour & (df.points_charted >= ESTABLISHED_PTS)
        for rate, den in RATES:
            typical = df.loc[est & (df[den] > 0), rate].median()
            floor = precision_floor(typical) if pd.notna(typical) else math.inf
            df.loc[tour & ~(df[den] >= floor), rate] = None
            if math.isfinite(floor):
                rows.append({"key": f"floor_{rate}_{g}", "value": float(floor)})
    whole = df[list(SERVE_PLOT)].notna().all(axis=1)
    df.loc[~whole, list(SERVE_PLOT)] = None
    # The serve plot's own note quotes its floor in second-serve points, the denominator that
    # binds for nearly everyone.
    by = {r["key"]: r["value"] for r in rows}
    for g in sorted(df.gender.dropna().unique()):
        second = [by.get(f"floor_{k}_{g}") for k in ("second_in_pct", "second_won_pct")]
        if all(v is not None for v in second):
            rows.append({"key": f"floor_serve_plot_{g}", "value": max(second)})
    # A figure is null or a rate; rates ship rounded like the rest of the table.
    rates = [r for r, _ in RATES]
    df[rates] = df[rates].astype(float).round(4)
    return df, rows


def _player_facts(con) -> pd.DataFrame:
    """Handedness, ace rate, and serve-in and serve-won rates per ``(gender, player)``.

    Hand is the modal R/L value across charted matches. Column-shifted upstream rows are
    ignored, and a tie (Marcelo Filippini, charted once each way) comes out null rather than
    as a coin toss.

    First serves in are over every point served, second serves in over the points where the
    first missed. The won rates use the same denominators, so second-serve points won counts
    double faults as losses. No double-fault rate ships: it equals
    ``(1 - second_in_pct) * (1 - first_in_pct)``. The rates come out raw, with their
    denominators; ``_apply_floors`` decides which print.
    """
    hands = con.execute(
        "WITH seen AS ("
        "  SELECT gender, player1 AS player, upper(trim(player1_hand)) AS hand FROM matches"
        "  UNION ALL"
        "  SELECT gender, player2, upper(trim(player2_hand)) FROM matches), "
        "voted AS ("
        "  SELECT gender, player, hand,"
        "         rank() OVER (PARTITION BY gender, player ORDER BY count(*) DESC) rk"
        "  FROM seen WHERE hand IN ('R', 'L') GROUP BY gender, player, hand) "
        # rank(), so a tie ranks both hands 1 and the HAVING drops the player (null hand).
        "SELECT gender, player, min(hand) AS hand FROM voted WHERE rk = 1 "
        "GROUP BY gender, player HAVING count(*) = 1").fetchall()
    tot = pd.DataFrame(con.execute(
        "SELECT gender, player, sum(CAST(serve_pts AS INT)), sum(CAST(aces AS INT)),"
        "       sum(CAST(first_in AS INT)), sum(CAST(dfs AS INT)),"
        "       sum(CAST(first_won AS INT)), sum(CAST(second_won AS INT)) "
        "FROM stats_overview WHERE set = 'Total' GROUP BY gender, player").fetchall(),
        columns=["gender", "player", "sp", "aces", "fi", "dfs", "fw", "sw"])
    second = tot.sp - tot.fi

    def rate(num, den):
        return (num / den).where(den > 0)

    serves = pd.DataFrame({
        "gender": tot.gender, "player": tot.player,
        "ace_rate": rate(tot.aces, tot.sp),
        "first_in_pct": rate(tot.fi, tot.sp),
        "second_in_pct": rate(second - tot.dfs, second),
        "first_won_pct": rate(tot.fw, tot.fi),
        "second_won_pct": rate(tot.sw, second),
        "serve_pts": tot.sp, "second_pts": second, "first_in_n": tot.fi,
    })
    facts = pd.DataFrame(hands, columns=["gender", "player", "hand"])
    return facts.merge(serves, on=["gender", "player"], how="outer")


# Every game in the corpus, with who served it and who won it. The winner is the winner of
# the last point, which agrees with the score-progression reading on 262,191 of 262,193 games
# and also works for a match's last game. Tiebreaks are dropped (more than one server in the
# game, or played at 6-6): 4,986 of 292,431 games.
_GAMES_SQL = """
WITH p AS (
  SELECT match_id, CAST(pt AS INT) AS pt, CAST(game_num AS INT) AS gn,
         gm1, gm2, svr, pt_winner
  FROM points WHERE svr IN (1, 2) AND pt_winner IN (1, 2)),
g AS (
  SELECT match_id, gn, count(DISTINCT svr) AS nsv, min(svr) AS svr,
         min(gm1) AS g1, min(gm2) AS g2, max(pt) AS last_pt
  FROM p GROUP BY match_id, gn),
decided AS (
  SELECT g.match_id, g.svr, p.pt_winner
  FROM g JOIN p ON p.match_id = g.match_id AND p.pt = g.last_pt
  WHERE g.nsv = 1 AND NOT (g.g1 = 6 AND g.g2 = 6))
SELECT m.gender,
       CASE WHEN d.svr = {mine} THEN m.player1 ELSE m.player2 END AS player,
       count(*) AS n,
       sum(CASE WHEN d.pt_winner {test} d.svr THEN 1 ELSE 0 END) AS won
FROM decided d JOIN matches m USING (match_id)
GROUP BY 1, 2
"""


def _game_rates(con) -> pd.DataFrame:
    """Hold and break rate per ``(gender, player)``, the ring's arc and tick.

    Games rather than points, since a serve edge that is small in points is large in games:
    the men's tour wins 64% of service points and holds 80% of service games.
    """
    hold = pd.DataFrame(
        con.execute(_GAMES_SQL.format(mine=1, test="=")).fetchall(),
        columns=["gender", "player", "serve_games", "holds"])
    brk = pd.DataFrame(
        con.execute(_GAMES_SQL.format(mine=2, test="<>")).fetchall(),
        columns=["gender", "player", "return_games", "breaks"])
    hold["hold_rate"] = (hold.holds / hold.serve_games).round(4)
    brk["break_rate"] = (brk.breaks / brk.return_games).round(4)
    return hold[["gender", "player", "hold_rate", "serve_games"]].merge(
        brk[["gender", "player", "break_rate", "return_games"]],
        on=["gender", "player"], how="outer")


# Points won on the return itself: the point ended on the second shot, the returner took it,
# and it was a winner. (A forced error on the second shot is the returner's own.)
_RETURN_WINNER_SQL = """
WITH r AS (
  SELECT m.gender,
         CASE WHEN p.svr = 1 THEN m.player2 ELSE m.player1 END AS player,
         pp.rally_len, pp.outcome, pp.server_won
  FROM points p
  JOIN points_parsed pp USING (match_id, pt)
  JOIN matches m USING (match_id)
  WHERE p.svr IN (1, 2) AND p.pt_winner IN (1, 2) AND pp.parse_ok)
SELECT gender, player,
       sum(CASE WHEN rally_len = 2 AND outcome = 'winner' AND NOT server_won
                THEN 1 ELSE 0 END) / CAST(count(*) AS DOUBLE) AS ret_winner_rate,
       count(*) AS ret_pts
FROM r GROUP BY gender, player
"""


# The career "average length of points won": mean strokes in the points the player won.
# Shipped only as the career anchor under the match figure (as a figure of its own it would
# repeat avg_rally_len, r ≈ 0.98), and counted like build_match_details._fold_point.
_WON_LEN_SQL = """
WITH w AS (
  SELECT m.gender,
         CASE WHEN pp.winner_by_notation = 1 THEN m.player1 ELSE m.player2 END AS player,
         pp.rally_len
  FROM points_parsed pp
  JOIN matches m USING (match_id)
  WHERE pp.parse_ok AND pp.winner_by_notation IN (1, 2) AND pp.rally_len IS NOT NULL)
SELECT gender, player, avg(rally_len) AS won_rally_len
FROM w GROUP BY gender, player HAVING count(*) >= {floor}
"""


def _won_point_len(con) -> pd.DataFrame:
    """Mean strokes in the points each ``(gender, player)`` won, across their charted matches."""
    rows = con.execute(_WON_LEN_SQL.format(floor=WON_LEN_POINTS)).fetchall()
    return pd.DataFrame(rows, columns=["gender", "player", "won_rally_len"])


_MIX_SQL = (
    "SELECT m.gender, m.player1, m.player2, p.svr, p.first_serve, p.second_serve, p.pt_winner "
    "FROM points p JOIN matches m USING (match_id) "
    "WHERE p.svr IN (1, 2) AND p.pt_winner IN (1, 2)"
)


def _shot_mix(con) -> pd.DataFrame:
    """Career shot mix per ``(gender, player)``: what they hit, and what each wing did.

    The career reading of the ten figures the charted-match panel prints, off the same stroke
    walk (``notation.fold_shot_mix``) so match and career count the same strokes. A Python
    walk of the whole corpus takes about ten seconds. Keyed by base name straight off
    ``matches``, so there's no era collapse. Raw, with the counts; ``_apply_floors`` decides
    which print.
    """
    acc: dict = defaultdict(blank_mix)
    cur = con.execute(_MIX_SQL)
    while batch := cur.fetchmany(200_000):
        for gender, p1, p2, svr, fs, ss, win in batch:
            point = parse_point(fs, ss, svr, win)
            if not point.parse_ok:
                continue
            names = {1: (gender, p1), 2: (gender, p2)}
            fold_shot_mix(point, lambda h: acc[names[h]])
    # Columns named even with no rows, so an empty corpus still yields every rate column.
    df = pd.DataFrame([{"gender": g, "player": p, **c} for (g, p), c in acc.items()],
                      columns=["gender", "player", *MIX_FIELDS])
    gs = df.fh_gs + df.bh_gs

    def rate(num, den):
        return (df[num] / den).where(den > 0)

    out = pd.DataFrame({"gender": df.gender, "player": df.player})
    # Wing shares and outcome rates, grouped the way the panel draws them.
    out["fh_share"] = rate("fh_gs", gs)
    out["fh_winner_pct"] = rate("fh_winners", df.fh_gs)
    out["fh_err_pct"] = rate("fh_errs", df.fh_gs)
    out["bh_share"] = rate("bh_gs", gs)
    out["bh_winner_pct"] = rate("bh_winners", df.bh_gs)
    out["bh_err_pct"] = rate("bh_errs", df.bh_gs)
    # The slice ships as a share only. Its winner rate is too rare to measure, and its error
    # rate is noisy (0.52 split-half) and mostly repeats the wing error rates (r ≈ 0.44).
    out["slice_pct"] = rate("slice_shots", df.rally_shots)
    out["net_pct"] = rate("net_shots", df.rally_shots)
    out["net_winner_pct"] = rate("net_winners", df.net_shots)
    out["net_err_pct"] = rate("net_errs", df.net_shots)
    # The counts the rates are over, for _apply_floors.
    for col, v in (("gs", gs), ("fh_gs", df.fh_gs), ("bh_gs", df.bh_gs),
                   ("rally_shots", df.rally_shots), ("net_shots", df.net_shots)):
        out[col] = v
    return out[["gender", "player", *MIX_RATES, *MIX_COUNTS]]


def _return_winners(con) -> pd.DataFrame:
    """Return-winner rate per ``(gender, player)``.

    Nearly uncorrelated with return points won (0.03 men, -0.01 women), so it adds something
    the ring doesn't. The men's rate halved from 2.8% before 2009 to 1.3% in the 2020s while
    the women's held near 2.5%, which fits serve-and-volley leaving the men's game. Not
    adjusted for era. Raw, with ``ret_pts``; ``_apply_floors`` decides whether it prints.
    """
    rows = con.execute(_RETURN_WINNER_SQL).fetchall()
    df = pd.DataFrame(rows, columns=["gender", "player", "ret_winner_rate", "ret_pts"])
    return df


# --- the ace, split by which delivery struck it ------------------------------------------
# First- and second-serve ace rates run about an order of magnitude apart, so the pooled rate
# hides which kind of server a player is. Each rate is on the denominator of its column in the
# serve plot:
#
#   first_ace_pct   over the first serves that landed, beside first_won_pct
#   second_ace_pct  over every point that reached a second serve, beside second_won_pct
#
# The panel divides both second-serve rates by second_in_pct (see serveSplit in matchup.js).
# Counted from the parsed notation, since stats_overview doesn't split aces by delivery.
# `second_serve` is non-empty when the first missed, the same test as
# build_match_details._fold_point.
_SERVE_ACE_SQL = """
WITH s AS (
  SELECT m.gender,
         CASE WHEN p.svr = 1 THEN m.player1 ELSE m.player2 END AS player,
         coalesce(trim(p.second_serve), '') <> '' AS second,
         pp.outcome
  FROM points p
  JOIN points_parsed pp USING (match_id, pt)
  JOIN matches m USING (match_id)
  WHERE p.svr IN (1, 2) AND p.pt_winner IN (1, 2) AND pp.parse_ok)
SELECT gender, player,
       sum(CASE WHEN NOT second AND outcome = 'ace' THEN 1 ELSE 0 END)
         / CAST(NULLIF(sum(CASE WHEN NOT second THEN 1 ELSE 0 END), 0) AS DOUBLE)
         AS first_ace_pct,
       sum(CASE WHEN second AND outcome = 'ace' THEN 1 ELSE 0 END)
         / CAST(NULLIF(sum(CASE WHEN second THEN 1 ELSE 0 END), 0) AS DOUBLE)
         AS second_ace_pct,
       sum(CASE WHEN NOT second THEN 1 ELSE 0 END) AS first_n,
       sum(CASE WHEN second THEN 1 ELSE 0 END) AS second_n
FROM s GROUP BY gender, player
"""


def _serve_aces(con) -> pd.DataFrame:
    """First- and second-serve ace rates per ``(gender, player)``, raw, with the serves each is
    over — see ``_SERVE_ACE_SQL``."""
    rows = con.execute(_SERVE_ACE_SQL).fetchall()
    return pd.DataFrame(rows, columns=["gender", "player", "first_ace_pct", "second_ace_pct",
                                       "first_n", "second_n"])


def _serve_placement() -> "tuple[pd.DataFrame | None, list]":
    """Per-side first-serve placement for the panel, plus the gates it has to respect.

    The mix is recency-weighted (``serve_tendencies`` step 7: a 10-match half-life predicts
    better than the career mix). ``n_eff`` is its effective sample size and ``reliable`` the
    gate already applied. ``matches`` is the player's own window: matches still carrying a
    tenth of the newest one's weight.
    """
    path = REPORTS / "serve_tendencies_players.csv"
    if not path.exists():
        return None, []
    df = pd.read_csv(path)
    df = df[(df.serve == "1st") & df.recent_n_eff.notna() & df.recent_wide.notna()]
    # Built column by column: the CSV has both the recent and the career mix, and renaming
    # one onto the other's name would ship duplicate columns.
    serve = pd.DataFrame({
        "player": df.player, "gender": df.gender, "side": df.side,
        "wide": df.recent_wide, "t": df.recent_t,
        "n_eff": df.recent_n_eff.astype(int),
        "matches": df.recent_matches.fillna(0).astype(int),
        "years": df.recent_years,
        "career_wide": df.wide, "career_t": df.t, "career_n": df.n,
        "reliable": df.reliable.fillna(0).astype(int),
        "drift_ratio": df.drift_ratio,
    })

    # Gates and tour baselines as meta rows, so the site never hardcodes a
    # threshold the experiment owns. meta is numeric key/value, read by prefix.
    rows = []
    mpath = REPORTS / "serve_tendencies_meta.csv"
    if mpath.exists():
        for r in pd.read_csv(mpath).to_dict("records"):
            g = r["gender"]
            for col in ("n80_wide", "n80_t", "rule_param", "recent_matches",
                        "tour_deuce_wide", "tour_deuce_t", "tour_ad_wide", "tour_ad_t"):
                rows.append({"key": f"serve_{col}_{g}", "value": float(r[col])})
    return serve, rows


# state_kind / resp_kind are the two strokes' kinds (drive / slice / net / other). The panel
# needs them so a volley isn't drawn with a bounce.
PATTERN_COLS = ["player", "gender", "family", "state", "response", "state_depth",
                "state_kind", "resp_kind",
                "inc_code", "resp_code", "lift", "count", "n_state", "evidence",
                "win_rate", "tour_win_rate", "field_share", "state_win_rate"]
# Extra columns the return family carries and the rally family has no meaning for.
# The panel draws the serve from them, so they must survive the trip as strings —
# an all-empty rally column would otherwise read back as NaN and print "nan".
PATTERN_SIDE_COLS = ["tier", "serve_side", "serve_dir"]


def _patterns() -> pd.DataFrame:
    """The two pattern families. ``rally`` comes from court_response (sides pooled);
    ``ret`` from serve_plus_one (the server's third ball, with service court and serve
    direction where the charting allows). If serve_plus_one hasn't run, court_response's
    pooled ``ret`` rows are used instead.
    """
    # Code columns are read as text; a blank makes a column float, and "6" becomes "6.0".
    codes = {c: str for c in ("inc_code", "resp_code", "serve_dir", "serve_side", "tier")}
    cr = pd.read_csv(REPORTS / "court_response_players.csv", dtype=codes)
    sp_path = REPORTS / "serve_plus_one_players.csv"
    if sp_path.exists():
        ret = pd.read_csv(sp_path, dtype=codes)
        ret = ret[ret.family == "ret"]
        cr = cr[cr.family != "ret"]
    else:
        ret = cr[cr.family == "ret"].copy()
        cr = cr[cr.family != "ret"]
        ret["tier"] = "pooled"
        ret["serve_side"] = ""
        ret["serve_dir"] = ""

    for col in PATTERN_SIDE_COLS:
        cr[col] = ""
    patterns = pd.concat([cr[PATTERN_COLS + PATTERN_SIDE_COLS],
                          ret[PATTERN_COLS + PATTERN_SIDE_COLS]], ignore_index=True)
    for col in ("inc_code", "resp_code", "state_kind", "resp_kind", *PATTERN_SIDE_COLS):
        patterns[col] = patterns[col].fillna("").astype(str)
    patterns["state_depth"] = patterns["state_depth"].fillna("")
    return patterns


def build() -> int:
    """(Re)create ``insights.duckdb`` from the DB + experiment CSVs. Returns player count."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    strength, mu = current_strength(con)
    cov = coverage(con)
    cov_years = pd.DataFrame(coverage_by_year(con),
                             columns=["gender", "player", "year", "matches", "points"])
    cov_matches = pd.DataFrame(coverage_by_match(con),
                               columns=["gender", "player", "year", "points", "seq"])
    charted = _charted_matches(con)
    facts = _player_facts(con)
    games = _game_rates(con)
    ret_win = _return_winners(con)
    serve_aces = _serve_aces(con)
    won_len = _won_point_len(con)
    mix = _shot_mix(con)
    con.close()

    # `current_strength` supplies the player list and the tour means in `meta`; its two rates
    # aren't shipped because nothing on the site reads them.
    summary = pd.DataFrame([
        {"gender": g, "player": p,
         "matches_charted": cov.get((g, p), {}).get("matches", 0),
         "points_charted": cov.get((g, p), {}).get("points", 0),
         "year_min": cov.get((g, p), {}).get("year_min"),
         "year_max": cov.get((g, p), {}).get("year_max")}
        for g, p in strength
    ])

    summary = summary.merge(facts, on=["player", "gender"], how="left")
    # Left-joined like the rest; _apply_floors withholds the rates under their floors below.
    summary = summary.merge(games, on=["player", "gender"], how="left")
    summary = summary.merge(ret_win, on=["player", "gender"], how="left")
    summary = summary.merge(serve_aces, on=["player", "gender"], how="left")
    # The ten shot-mix rates.
    summary = summary.merge(mix, on=["player", "gender"], how="left")

    # Coverage by season for the charted-history chart, limited to players in the summary.
    years = cov_years.merge(summary[["gender", "player"]], on=["gender", "player"])
    years = years.astype({"year": "int32", "matches": "int32", "points": "int32"})

    # Coverage by match, for splitting each season bar; ``seq`` is play order within the
    # season.
    matches_by_year = cov_matches.merge(summary[["gender", "player"]], on=["gender", "player"])
    matches_by_year = matches_by_year.astype(
        {"year": "int32", "points": "int32", "seq": "int32"})

    # style_confident travels with the archetype, and the panel must respect it: for about a
    # third of players the two nearest archetypes fit equally well. The archetype stays
    # latest-era; avg_rally_len is point-weighted across eras (see _collapse).
    clusters = _collapse(pd.read_csv(REPORTS / "player_style_clusters.csv")
                         [["player", "gender", "archetype", "style_margin",
                           "style_confident", "avg_rally_len", "n_points"]],
                         mean_over={"avg_rally_len": "n_points"}).drop(columns="n_points")
    summary = summary.merge(clusters, on=["player", "gender"], how="left")

    # Won point length, read straight off the point corpus by base name (see _WON_LEN_SQL).
    summary = summary.merge(won_len, on=["player", "gender"], how="left")

    # Variety ships for every player shot_language scored, floored here like the rest.
    lang = pd.read_csv(REPORTS / "shot_language_players.csv")
    lang = lang[lang.strokes >= VARIETY_STROKES][["player", "gender", "bits"]]
    summary = summary.merge(lang, on=["player", "gender"], how="left")

    # Court-state response profiles: rally family from court_response, return family from
    # serve_plus_one (see _patterns).
    patterns = _patterns()

    # No shot-quality figure from class_relative_wpa ships: avg_wpa_lost is mostly rally
    # length (r ≈ -0.85), and the class-relative residual is no better. See
    # reports/class_relative_wpa.md.

    # Shot-making triggers: green lights by aggressive shot frequency lift, traps by how far
    # conversion falls below the player's norm. See experiments/shot_triggers.
    tr = pd.read_csv(REPORTS / "shot_triggers.csv")
    greens = (tr[tr.tag == "green"].sort_values("att_lift", ascending=False)
              .groupby(["player", "gender"]).head(3))
    traps = (tr[tr.tag == "trap"].sort_values("conv_delta")
             .groupby(["player", "gender"]).head(3))
    # ``attempts`` ships beside ``n``: n is the frequency's denominator, attempts (about a
    # third of n) the conversion's.
    triggers = pd.concat([greens, traps])[
        ["player", "gender", "tag", "context", "att_rate", "att_lift",
         "conversion", "conv_delta", "n", "attempts"]]

    # No 3-4 shot tier ships: only two of 1,752 three-shot candidates survive, both for retired
    # players. See experiments/rally_patterns.

    # Opening cues by service court: the same measure as the pooled triggers, but against the
    # player's norm for that shot on that court, since a wide serve opens opposite wings on the
    # two sides. FDR-corrected and cross-validated like the pooled table.
    openings = pd.DataFrame()
    op_path = REPORTS / "shot_triggers_openings.csv"
    if op_path.exists():
        op = pd.read_csv(op_path)
        if len(op):
            og = (op[op.tag == "green"].sort_values("att_lift", ascending=False)
                  .groupby(["player", "gender"]).head(2))
            ot = (op[op.tag == "trap"].sort_values("conv_delta")
                  .groupby(["player", "gender"]).head(2))
            openings = pd.concat([og, ot])[
                ["player", "gender", "side", "role", "anchor", "context", "tag",
                 "att_rate", "att_lift", "conversion", "conv_delta", "n", "attempts"]]

    # ``sigma`` isn't shipped: it mostly tracks rally length and a serve-volley artifact, and
    # says nothing about whether the aggression pays. ``trig_att_rate`` covers the question.
    tp = pd.read_csv(REPORTS / "shot_triggers_players.csv")[
        ["player", "gender", "att_rate", "conversion", "n_traps"]].rename(
        columns={"att_rate": "trig_att_rate", "conversion": "trig_conversion"})
    summary = summary.merge(tp, on=["player", "gender"], how="left")

    # Serve placement (serve_tendencies). Wide and T only: charters disagree on body serves by
    # ±4-6%, so body is left out and the two don't sum to 100%.
    serve, serve_meta = _serve_placement()
    if serve is not None:
        bp = pd.read_csv(REPORTS / "serve_tendencies_leverage.csv")
        bp = bp[(bp.direction == "wide") & (bp.bucket == "break_pt")][
            ["player", "gender", "delta", "sig", "n"]].rename(
            columns={"delta": "serve_bp_wide_delta", "sig": "serve_bp_sig",
                     "n": "serve_bp_n"})
        summary = summary.merge(bp, on=["player", "gender"], how="left")

    # Every rate under its floor goes null here; then the counts the panel doesn't read go.
    summary, floor_meta = _apply_floors(summary)
    counts = {den for _, den in RATES} - set(SHIPPED_COUNTS)
    summary = summary.drop(columns=sorted(counts))
    # The tour bands under the figures are cut over the same established players the floors
    # are read off, so one-match readings don't widen them.
    floor_meta.append({"key": "floor_band_points", "value": float(ESTABLISHED_PTS)})

    meta = pd.DataFrame([{"key": f"mu_{g}", "value": round(v, 5)} for g, v in mu.items()]
                        + floor_meta + serve_meta)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)     # fresh file: dropped tables must not ship forever
    out = duckdb.connect(str(OUT))
    tables = [("player_summary", summary), ("player_triggers", triggers),
              ("player_patterns", patterns), ("player_openings", openings),
              ("player_years", years), ("player_matches", matches_by_year), ("meta", meta),
              ("charted_matches", charted)]
    if serve is not None:
        tables.append(("player_serve", serve))
    for name, df in tables:
        out.register(f"_{name}", df)
        out.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _{name}")
    out.close()
    return len(summary)
