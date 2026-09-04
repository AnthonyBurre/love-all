"""Build the compact ``insights.duckdb`` the Pages site queries in-browser via DuckDB-WASM.

A small projection of the main DB — one row per charted player — assembled from the
experiment CSVs + the graduated library, keyed by **base player name** (era-split
entities are collapsed to their most recent era = current form). Aggregates only, so it
stays small enough to ship; nothing is committed (it lands under gitignored ``data/``).

Prereq: the experiments have been run so their CSVs exist in ``reports/`` (the CI
insights workflow runs them first). Run: ``match-charting-project site build-insights``.
"""

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
from match_charting_project.paths import DB_PATH, PROJECT_ROOT
from match_charting_project.shots.notation import blank_mix, fold_shot_mix, parse_point
from match_charting_project.winprob_match import current_strength

REPORTS = PROJECT_ROOT / "reports"
# The shot-mix rate columns, in the order the panel's figure column prints them. Named once
# so the empty-corpus fallback and any reader of this file see the same list.
MIX_RATES = ("fh_share", "fh_winner_pct", "fh_err_pct",
             "bh_share", "bh_winner_pct", "bh_err_pct",
             "slice_pct",
             "net_pct", "net_winner_pct", "net_err_pct")
OUT = PROJECT_ROOT / "data" / "insights.duckdb"
_ERA_RE = re.compile(r"^(?P<base>.+) \((?P<y0>\d{4})[–-](?P<y1>\d{4})\)$")
# Only recent slam/1000 identities ship: the site archives completed events going forward,
# never older ones, so their per-match charting status is all the fast path can ever need.
_CHARTED_SINCE = date.today().year - 2


def _base(entity: str) -> "tuple[str, int]":
    m = _ERA_RE.match(str(entity))
    return (m["base"], int(m["y1"])) if m else (str(entity), 0)


def _collapse(df: pd.DataFrame, mean_over: "dict | None" = None) -> pd.DataFrame:
    """Collapse era entities to base names, keeping the latest era per (gender, player).

    Latest-era is right for the things this is mostly used for — an archetype and its
    confidence flag are a claim about how someone plays, and for a split career the
    current answer is the one worth printing.

    It is wrong for a *measurement* the panel prints beside a career-wide denominator.
    ``mean_over`` names columns to average across a player's eras instead, weighted by
    the ``weight`` column, so the figure covers the same matches the coverage band
    above it counts. Rally length needed this: Connors' two eras run 4.90 and 6.16, and
    the panel printed 6.2 from 2,776 points directly beside a charted-history line
    reading 7,309 — under a key claiming the figure covers every charted point the
    player appeared in. Across the 35 split careers the two eras differ by 0.351 on
    average, which is 44% of the tour's whole interquartile spread, and by up to 1.266.
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


def _player_facts(con) -> pd.DataFrame:
    """Handedness, ace rate and the two serve-in rates per ``(gender, player)``, from the DB.

    All are facts about the player rather than findings about them, so none comes through
    an experiment: they are read here and shipped beside the rates.

    Hand is the modal value across their charted matches, not the first one seen. A
    handful of rows in the upstream matches CSV are column-shifted (the hand column
    holding a date or a tie name), so anything that isn't R or L is dropped before the
    vote rather than allowed to win one — and a player charted only in those rows comes
    out null, which the panel prints as nothing.

    Ace rate is over service points across every charted match. The two serve-in rates are
    each over the serves that were actually hit: first serves over every point served,
    second serves over the points where the first one missed.

    The two serve-won rates sit on those same denominators, so each pairs with the in-rate
    above it: how often the delivery landed, then how often landing it won the point. A
    second-serve point is counted lost when the second serve missed, which is why the
    denominator there is every point that reached a second serve rather than every second
    serve that landed — a double fault is a service point lost, and excluding it would
    quote a rate over the subset of second serves the player got away with.

    They are the half of the serve this panel never had. An in-rate alone does not say
    whether the serve was worth landing: in the 2025 Wimbledon final Alcaraz landed 53%
    of first serves, which reads as a collapse, and won 75% of them, exactly as many as
    Sinner did off 62%.

    No double-fault rate ships. The panel still prints one, but it is exactly
    ``(1 - second_in_pct) * (1 - first_in_pct)`` — the share of points that reach a second
    serve, times the share of those the second serve misses — so shipping it as well would
    be shipping the same fact twice and inviting the two copies to disagree. Recovered from
    the two rounded rates it is out by at most 0.003pp, against a figure printed to a tenth.

    They need the floor because none is shrunk toward anything: over a single charted match
    a couple of aces in a short set reads as a 15% ace rate. 200 service points is about
    two matches.
    """
    hands = con.execute(
        "WITH seen AS ("
        "  SELECT gender, player1 AS player, upper(trim(player1_hand)) AS hand FROM matches"
        "  UNION ALL"
        "  SELECT gender, player2, upper(trim(player2_hand)) FROM matches), "
        "voted AS ("
        "  SELECT gender, player, hand,"
        "         row_number() OVER (PARTITION BY gender, player ORDER BY count(*) DESC) rn"
        "  FROM seen WHERE hand IN ('R', 'L') GROUP BY gender, player, hand) "
        "SELECT gender, player, hand FROM voted WHERE rn = 1").fetchall()
    serves = con.execute(
        "SELECT gender, player,"
        "       sum(CAST(aces AS INT)) / CAST(sum(CAST(serve_pts AS INT)) AS DOUBLE)"
        "         AS ace_rate,"
        "       sum(CAST(first_in AS INT)) / CAST(sum(CAST(serve_pts AS INT)) AS DOUBLE)"
        "         AS first_in_pct,"
        "       (sum(CAST(serve_pts AS INT)) - sum(CAST(first_in AS INT)) - sum(CAST(dfs AS INT)))"
        "         / CAST(NULLIF(sum(CAST(serve_pts AS INT)) - sum(CAST(first_in AS INT)), 0)"
        "                AS DOUBLE) AS second_in_pct,"
        "       sum(CAST(first_won AS INT))"
        "         / CAST(NULLIF(sum(CAST(first_in AS INT)), 0) AS DOUBLE) AS first_won_pct,"
        "       sum(CAST(second_won AS INT))"
        "         / CAST(NULLIF(sum(CAST(serve_pts AS INT)) - sum(CAST(first_in AS INT)), 0)"
        "                AS DOUBLE) AS second_won_pct "
        "FROM stats_overview WHERE set = 'Total' "
        "GROUP BY gender, player HAVING sum(CAST(serve_pts AS INT)) >= 200").fetchall()
    facts = pd.DataFrame(hands, columns=["gender", "player", "hand"])
    return facts.merge(
        pd.DataFrame(serves, columns=["gender", "player", "ace_rate",
                                      "first_in_pct", "second_in_pct",
                                      "first_won_pct", "second_won_pct"]),
        on=["gender", "player"], how="outer")


# A hold or a break needs enough games behind it to mean anything. 100 on each side is
# roughly four matches of serving, and it is a floor on nonsense rather than a claim of
# precision — the same job RATE_MIN_PTS does for the rates these marks sit on. At the
# panel's own 2,000-charted-point gate it excludes nobody: the thinnest player who gets a
# ring has 144 service games and 148 return games.
MIN_GAMES = 100

# Every game in the corpus, with who served it and who won it.
#
# The winner is the winner of the game's last point. That is true by definition for a game
# that finished, and checked rather than assumed: against the independent reading — whose
# game count went up on the first point of the next game — the two agree on 262,191 of
# 262,193 games played inside a set. The two that disagree are charting errors, and the
# rule is kept because the score-progression reading cannot score the last game of a match
# at all, having no next game to read.
#
# Tiebreaks are dropped. Both players serve in one, so it is nobody's hold to lose, and
# the notation records the real server per point — which is also how they are found:
# more than one server in a game, or a game played at 6-6. That is 4,986 of 292,431 games.
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
GROUP BY 1, 2 HAVING count(*) >= {floor}
"""


def _game_rates(con) -> pd.DataFrame:
    """Hold and break rate per ``(gender, player)`` — the panel's two ring marks.

    Games rather than points, which is the whole reason they are worth drawing beside the
    rings: a serve edge measured in points is small and measured in games is not. The
    charted tour wins 64% of service points and holds 80% of service games (men), 57% and
    66% (women), and the same lever works the other way on return — 36% of return points
    becomes 20% of return games broken. The mark on each ring is that conversion, per
    player, on the ring's own scale.
    """
    hold = pd.DataFrame(
        con.execute(_GAMES_SQL.format(mine=1, test="=", floor=MIN_GAMES)).fetchall(),
        columns=["gender", "player", "serve_games", "holds"])
    brk = pd.DataFrame(
        con.execute(_GAMES_SQL.format(mine=2, test="<>", floor=MIN_GAMES)).fetchall(),
        columns=["gender", "player", "return_games", "breaks"])
    hold["hold_rate"] = (hold.holds / hold.serve_games).round(4)
    brk["break_rate"] = (brk.breaks / brk.return_games).round(4)
    return hold[["gender", "player", "hold_rate", "serve_games"]].merge(
        brk[["gender", "player", "break_rate", "return_games"]],
        on=["gender", "player"], how="outer")


# A return-winner rate is a small number over a large denominator, so its floor is set by how
# many events sit behind it rather than by how many points do: at the modern men's rate of
# about 1.2%, 1,000 return points is a dozen return winners. Below that the figure is mostly
# the charter's rounding. It costs 5 of the 363 players who get a ring, and they go without
# the line and the wedge rather than with a fragile version of both.
MIN_RETURN_PTS = 1000

# Points the returner won on the return itself: the point ended on the second shot, the
# returner took it, and the notation calls it a winner. That is the whole rally — a serve and
# one ball back — so there is no forced-error case to add: a forced error on the second shot is
# the returner's own, and the server wins it.
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
                THEN 1 ELSE 0 END) / CAST(count(*) AS DOUBLE) AS ret_winner_rate
FROM r GROUP BY gender, player HAVING count(*) >= {floor}
"""


# The career reading of the charted match's "average length of points won": mean strokes in
# the points this player actually won, over every charted match of theirs.
#
# It ships as the anchor under that match figure and nowhere else. As a figure in its own
# right it would be the panel saying the same thing twice — across the players who qualify it
# correlates 0.989 (men) and 0.981 (women) with avg_rally_len, which the column already
# prints, so a reader comparing two players on it would be comparing their point lengths
# through a second name for them. Under a match figure it is doing the one job that
# correlation does not spoil: saying whether 4.4 shots was long or short *for this player*.
#
# Counted like the match figure it anchors, so the two are the same measurement over
# different windows: parsed points only, strokes over the points the player won — see
# build_match_details._fold_point.
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

# Won points behind the career figure. Rally length has a standard deviation near 3.3 strokes,
# so the standard error of this mean is 3.3/sqrt(n) — at a thousand won points that is 0.10,
# which is one unit of the single decimal the figure prints at. Below it the anchor would be
# moving in the digit it is shown in.
MIN_WON_PTS = 1000


def _won_point_len(con) -> pd.DataFrame:
    """Mean strokes in the points each ``(gender, player)`` won, across their charted matches."""
    rows = con.execute(_WON_LEN_SQL.format(floor=MIN_WON_PTS)).fetchall()
    return pd.DataFrame(rows, columns=["gender", "player", "won_rally_len"])


# The shot mix needs enough strokes of the kind it is measured over to be a rate rather than
# a run of luck. 800 is the number variety already uses for the same unit — charted strokes —
# and at the panel's own 2,000-point ring gate it excludes nobody: the thinnest player who
# gets a ring has 3,171 rally strokes, 1,243 forehands and 1,360 backhands. It bites below
# that, where the figure column still prints without the rings, and that is where it is for.
#
# It is a floor on obvious nonsense and not a claim of precision. These are career charted
# rates, never adjusted for the opponents a volunteer chose to chart, exactly like the two
# rates on the rings.
MIN_MIX_SHOTS = 800

# The net group gets its own floor, because nobody hits 800 volleys: the median player in this
# corpus hits 28 net shots in their whole charted record, and the median player who gets a ring
# hits 336. 200 is where those rates stop being a coin toss — at the tour's ~10% net error rate
# it is about twenty missed volleys behind the figure, and its standard error is about half the
# spread the middle of the tour occupies. Roughly three quarters of the players who get a ring
# clear it.
#
# It is the loosest floor on the panel, and the two rates it gates are the least steady figures
# on it: split-half over alternate matches, the net winner rate reads 0.80 and the net error
# rate 0.52, against 0.72–0.81 for the wing rates and 0.90+ for the shares. The error rate is
# the one that pays for its noise — it is uncorrelated with the winner rate beside it (r =
# -0.00), so what coming forward costs is not recoverable from what it earns, and no other
# figure on the panel carries it. Raising the floor is the only lever on it and there is
# nothing to raise it to: 400 leaves 159 players and 800 leaves 79.
MIN_STROKE_SHOTS = 200

_MIX_SQL = (
    "SELECT m.gender, m.player1, m.player2, p.svr, p.first_serve, p.second_serve, p.pt_winner "
    "FROM points p JOIN matches m USING (match_id) "
    "WHERE p.svr IN (1, 2) AND p.pt_winner IN (1, 2)"
)


def _shot_mix(con) -> pd.DataFrame:
    """Career shot mix per ``(gender, player)``: what they hit, and what each wing did.

    The career reading of the eight figures the charted-match panel prints from the sidecar,
    off the same shared stroke walk (``notation.fold_shot_mix``), so the two are one
    measurement over two windows — the match's own rate, and this underneath it as the anchor
    that says whether that rate was ordinary for the player.

    A whole-corpus walk in Python, which sounds worse than it is: 1.85M points decode in about
    ten seconds, against the minutes the experiment CSVs feeding the rest of this file already
    cost. There is no SQL shortcut worth having — the counts are per stroke and the notation
    has to be tokenized to find them, and doing it here rather than in a second decoder is
    what keeps the career figure and the match figure counting the same strokes.

    Keyed by base player name straight off ``matches``, like the return-winner rate beside it,
    so no era collapse applies: this is the player's whole charted record, which is the window
    the coverage band at the top of the panel counts.
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
    df = pd.DataFrame([{"gender": g, "player": p, **c} for (g, p), c in acc.items()])
    if df.empty:
        return pd.DataFrame(columns=["gender", "player", *MIX_RATES])
    gs = df.fh_gs + df.bh_gs

    def rate(num, den, floor):
        """A share, null under the floor — a rate off too few strokes is not shipped."""
        return (df[num] / den).where(den >= floor).round(4)

    out = pd.DataFrame({"gender": df.gender, "player": df.player})
    # Grouped the way the panel draws them: which hand, then what kind of ball. The two
    # shares are complements by construction, and both ship — each group's outcome rates are
    # read against how often that stroke is played at all, so a group without its own share
    # row is a group missing the thing its other two rows are measured against.
    out["fh_share"] = rate("fh_gs", gs, MIN_MIX_SHOTS)
    out["fh_winner_pct"] = rate("fh_winners", df.fh_gs, MIN_MIX_SHOTS)
    out["fh_err_pct"] = rate("fh_errs", df.fh_gs, MIN_MIX_SHOTS)
    out["bh_share"] = rate("bh_gs", gs, MIN_MIX_SHOTS)
    out["bh_winner_pct"] = rate("bh_winners", df.bh_gs, MIN_MIX_SHOTS)
    out["bh_err_pct"] = rate("bh_errs", df.bh_gs, MIN_MIX_SHOTS)
    # The slice ships as a share and nothing else — how often the player chooses the ball,
    # which is the archetype signal and the steadiest figure in the block (0.90 split-half over
    # alternate matches). Neither outcome rate survived the same test the return-winner rate
    # answers to.
    #
    # The winner rate fails outright: the tour's median is 0.89% and the middle half spans 0.56
    # points, so at any floor players clear, one or two shots carry the figure and its standard
    # error is wider than the spread it would be read against.
    #
    # The error rate fails on two counts at once. It splits half at 0.52 — about a third of the
    # spread a reader would see on its strip is sampling noise, against 0.72–0.81 for the wing
    # rates drawn above it — and it correlates 0.44 with the backhand error rate and 0.43 with
    # the forehand one, so what it does say is largely the groundstroke square saying it again.
    # A 400-slice floor would carry it (0.78) at 356 players and an 800 one comfortably (0.90)
    # at 217, but a rate bought at that price has to be telling the reader something the panel
    # does not already have, and this one is not.
    out["slice_pct"] = rate("slice_shots", df.rally_shots, MIN_MIX_SHOTS)
    out["net_pct"] = rate("net_shots", df.rally_shots, MIN_MIX_SHOTS)
    out["net_winner_pct"] = rate("net_winners", df.net_shots, MIN_STROKE_SHOTS)
    out["net_err_pct"] = rate("net_errs", df.net_shots, MIN_STROKE_SHOTS)
    return out


def _return_winners(con) -> pd.DataFrame:
    """Return-winner rate per ``(gender, player)`` — the return ring's outright-win core.

    The return side of the ace: a point the player won without playing a rally for it. It is
    the one figure on these two rings that says something the arc beside it does not — it
    correlates 0.03 (men) and -0.01 (women) with return points won, where an ace rate largely
    explains why a server's arc is long.

    Era matters more here than anywhere else on the panel, and it is real tennis rather than
    charting drift. The men's rate has halved, 2.8% before 2009 to 1.3% in the 2020s, while
    the women's has held near 2.5% throughout — which is what serve-and-volley leaving the
    men's game looks like from the returner's end: a return that has to pass an incoming
    server is a winner, and a return against a baseliner starts a rally. Both tours are
    charted by the same volunteers under the same conventions, so a judgment shift would have
    moved both. These are career charted rates and are not adjusted for it.
    """
    rows = con.execute(_RETURN_WINNER_SQL.format(floor=MIN_RETURN_PTS)).fetchall()
    df = pd.DataFrame(rows, columns=["gender", "player", "ret_winner_rate"])
    df["ret_winner_rate"] = df.ret_winner_rate.round(4)
    return df


# --- the ace, split by which delivery struck it ------------------------------------------
# An ace is the one point a serve wins on its own, and which serve won it is most of what the
# figure means: the first delivery is hit to be unreturnable and the second one is not, so a
# player's two rates run about an order of magnitude apart and averaging them into one number
# hides which of the two the player is.
#
# Each rate sits on the denominator of the column it is drawn inside on the serve plot, which
# is what lets it be drawn there at all — the ace share is a part of what that delivery won,
# so the two have to be shares of the same thing:
#
#   first_ace_pct   over the first serves that landed, beside first_won_pct
#   second_ace_pct  over every point that reached a second serve, beside second_won_pct
#
# The second one is not over the second serves that *landed*, for the same reason
# second_won_pct is not: a double fault is a point that reached a second serve, and the panel
# divides both rates back out by second_in_pct to get the landed-serve reading the plot draws
# (see serveSplit in matchup.js). Keeping the two on one denominator is what makes that one
# division rather than two conventions.
#
# Counted off the parsed notation rather than off stats_overview, which totals aces without
# saying which delivery struck them. `second_serve` is non-empty exactly when the first one
# missed, which is the same test build_match_details._fold_point applies point by point — so
# the career rate and the match rate under it are one measurement over two windows.
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
         AS second_ace_pct
FROM s GROUP BY gender, player HAVING count(*) >= {floor}
"""

# The same 200 service points the pooled ace rate needs in _player_facts, for the same reason:
# nothing here is shrunk toward anything, so over one short set a couple of aces reads as a
# 15% rate. The split does not want a floor of its own — it is the pooled figure cut in two,
# and a player who has earned one has earned both halves of it.
MIN_ACE_PTS = 200


def _serve_aces(con) -> pd.DataFrame:
    """First- and second-serve ace rates per ``(gender, player)`` — see ``_SERVE_ACE_SQL``."""
    rows = con.execute(_SERVE_ACE_SQL.format(floor=MIN_ACE_PTS)).fetchall()
    df = pd.DataFrame(rows, columns=["gender", "player", "first_ace_pct", "second_ace_pct"])
    return df.round({"first_ace_pct": 4, "second_ace_pct": 4})


def _serve_placement() -> "tuple[pd.DataFrame | None, list]":
    """Per-side serve placement for the panel, plus the gates it has to respect.

    The shipped mix is the recency-weighted one (``serve_tendencies`` step 7: a
    10-match half-life predicts a player's next matches better than their career
    average, because placement drifts), and ``n_eff`` is its effective sample
    size — the number the reliability gate applies to, since a decay weighting
    has no raw denominator. ``reliable`` is that gate already applied.

    ``matches`` is how much history that weighting actually reaches for this
    player: the matches still carrying a tenth of the newest one's weight. It
    ships per player because that is what the panel says out loud, and the same
    figure in the meta rows below is the *largest* window on the tour — printing
    that one against every player overstates the window for the third of them
    whose careers are shorter than it.
    """
    path = REPORTS / "serve_tendencies_players.csv"
    if not path.exists():
        return None, []
    df = pd.read_csv(path)
    df = df[(df.serve == "1st") & df.recent_n_eff.notna() & df.recent_wide.notna()]
    # Built column by column rather than renamed: the CSV carries both the recent
    # and the career mix, and renaming one onto the other's name silently ships
    # duplicate columns with the career values winning.
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


# state_kind / resp_kind are the two strokes' kinds (drive / slice / net / other). They
# read as part of the prose, but the panel needs them as data: a volley is met in the air,
# and a drawing that cannot tell one from a drive draws a bounce under a ball that never
# landed. Both experiments have always emitted them.
PATTERN_COLS = ["player", "gender", "family", "state", "response", "state_depth",
                "state_kind", "resp_kind",
                "inc_code", "resp_code", "lift", "count", "n_state", "evidence",
                "win_rate", "tour_win_rate", "field_share", "state_win_rate"]
# Extra columns the return family carries and the rally family has no meaning for.
# The panel draws the serve from them, so they must survive the trip as strings —
# an all-empty rally column would otherwise read back as NaN and print "nan".
PATTERN_SIDE_COLS = ["tier", "serve_side", "serve_dir"]


def _patterns() -> pd.DataFrame:
    """The two pattern families, from the two experiments that own them.

    ``rally`` is court_response's: a player's answer to an incoming ball, sides
    pooled because a mid-rally ball has no side. ``ret`` is serve_plus_one's: the
    server's third ball, with the service court and the serve's direction in the
    state wherever the player's charting funds them.

    serve_plus_one is optional. It is the newer of the two, and a stale checkout or
    a half-run pipeline should ship the panel with court_response's pooled return
    rows rather than with no return section at all.
    """
    # The code columns are read as text, never inferred. They are digits, and a column
    # with any blank in it infers as float — which turns serve direction "6" into "6.0",
    # matches none of the renderer's cases, and silently drops the serve from the drawing.
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

    summary = pd.DataFrame([
        {"gender": g, "player": p, "serve_rate": round(sv, 4), "return_rate": round(rt, 4),
         "matches_charted": cov.get((g, p), {}).get("matches", 0),
         "points_charted": cov.get((g, p), {}).get("points", 0),
         "year_min": cov.get((g, p), {}).get("year_min"),
         "year_max": cov.get((g, p), {}).get("year_max")}
        for (g, p), (sv, rt) in strength.items()
    ])

    summary = summary.merge(facts, on=["player", "gender"], how="left")
    # Hold and break rate ride beside the point rates they are the game-level reading of.
    # Left-joined like the rest: below MIN_GAMES they come through null and the ring simply
    # goes without its mark, the same way a thin server's arc goes without its ace wedge.
    summary = summary.merge(games, on=["player", "gender"], how="left")
    summary = summary.merge(ret_win, on=["player", "gender"], how="left")
    # The ace rate the panel already carried, cut by which delivery struck it — the two shares
    # the serve plot deepens the foot of each column with. Left-joined like the rest.
    summary = summary.merge(serve_aces, on=["player", "gender"], how="left")
    # The shot mix, eight rates wide. Left-joined like everything else, so a player under a
    # floor comes through null and the panel drops that row rather than printing a rate off
    # forty forehands. Eight doubles over ~1,700 rows is a few tens of KB in a file every
    # visitor downloads whole, which is what these are worth: they are the only figures on the
    # panel that say what a player actually hits.
    summary = summary.merge(mix, on=["player", "gender"], how="left")

    # The same coverage the summary carries as four numbers, cut by season, for the panel's
    # charted-history chart. Inner-joined to the summary so the table only holds players the
    # site can actually open a panel for — the charting corpus reaches a long tail of players
    # who never appear in a draw, and their year rows would be most of the file.
    years = cov_years.merge(summary[["gender", "player"]], on=["gender", "player"])
    years = years.astype({"year": "int32", "matches": "int32", "points": "int32"})

    # The same coverage at match resolution: one row per charted match, for the segments the
    # history chart splits each season bar into. Same inner join as ``years`` — panel-openable
    # players only — and the two agree by construction, since both come out of the one shared
    # row set in ``coverage_by_*``. ``seq`` is the play order within the season, for laying the
    # segments out left to right.
    matches_by_year = cov_matches.merge(summary[["gender", "player"]], on=["gender", "player"])
    matches_by_year = matches_by_year.astype(
        {"year": "int32", "points": "int32", "seq": "int32"})

    # style_confident travels with the archetype, and the panel is required to respect
    # it: style is a continuum, the clustering's silhouette sits near 0.12, and for a
    # third of entities the nearest two archetypes fit about equally well. Those are the
    # ones whose label flipped wholesale when a fifth of a percent of the corpus moved,
    # so shipping the name without the flag would be shipping the unstable half as
    # though it were the stable half.
    # avg_rally_len travels with the archetype because it is the same measurement pass:
    # mean strokes in the points the player appeared in, keyed by the same era entity. It
    # It is the panel's profile-column figure; see the class_relative_wpa note below for why
    # no shot-quality score stands there instead.
    # avg_rally_len is point-weighted across a split career; the archetype and its
    # confidence flag stay latest-era. The two want different things from the same row —
    # see _collapse — and n_points is the weight because it is the denominator the figure
    # was computed over in the first place.
    clusters = _collapse(pd.read_csv(REPORTS / "player_style_clusters.csv")
                         [["player", "gender", "archetype", "style_margin",
                           "style_confident", "avg_rally_len", "n_points"]],
                         mean_over={"avg_rally_len": "n_points"}).drop(columns="n_points")
    summary = summary.merge(clusters, on=["player", "gender"], how="left")

    # Beside avg_rally_len rather than with it: that one is point-weighted across a split
    # career and collapsed from the clustering's era entities, this one is read straight off
    # the point corpus by base name. They answer different questions and only one of them is
    # ever on screen at a time — see _WON_LEN_SQL.
    summary = summary.merge(won_len, on=["player", "gender"], how="left")

    lang = pd.read_csv(REPORTS / "shot_language_players.csv")[["player", "gender", "bits"]]
    summary = summary.merge(lang, on=["player", "gender"], how="left")

    # Court-state response profiles: the player's stable, hand-normalized answers to a given
    # incoming ball. Preferred over raw signature pairs, which mostly surface generic rally
    # geometry and handedness artifacts — see experiments/court_response.
    #
    # Two experiments feed one table, split by family. The rally family is
    # court_response's. The return family — the server's third ball — comes from
    # serve_plus_one instead, which asks the same question with the service court and
    # the serve's direction in the state, at whatever resolution each player's charting
    # funds. court_response still computes its own ret family for its report; it just
    # does not ship it, since the two would describe one shot two ways on one page.
    patterns = _patterns()

    # Nothing from class_relative_wpa is merged here: no shot-quality figure survives its own
    # validation. WPA telescopes within a point, so avg_wpa_lost is identically (win
    # probability conceded per point) / (strokes per point) and the second factor dominates —
    # it correlates -0.87 (men) / -0.83 (women) with rally length. The class-relative residual
    # is no better: it correlates -0.99 with the score it is taken from and 66% of its variance
    # is still rally length. reports/class_relative_wpa.{csv,md} keep the full record; this
    # file ships what the panel renders.

    # Shot-making triggers (shot_triggers experiment): green lights by aggressive shot
    # frequency lift, traps by how far conversion falls below the player's norm. One book,
    # not separate winner and error books — see experiments/shot_triggers.
    tr = pd.read_csv(REPORTS / "shot_triggers.csv")
    greens = (tr[tr.tag == "green"].sort_values("att_lift", ascending=False)
              .groupby(["player", "gender"]).head(3))
    traps = (tr[tr.tag == "trap"].sort_values("conv_delta")
             .groupby(["player", "gender"]).head(3))
    # ``attempts`` ships alongside ``n`` because they are the denominators of two
    # different numbers on the card and the panel was printing only the first. ``n`` is
    # the strokes played from that lead-up, which is what the frequency is over;
    # ``attempts`` is the aggressive shots among them, which is what the conversion is
    # over — and it is the smaller and more fragile of the two by roughly a factor of
    # three, so a card labelled n=93 was resting its conversion claim on 33 shots.
    triggers = pd.concat([greens, traps])[
        ["player", "gender", "tag", "context", "att_rate", "att_lift",
         "conversion", "conv_delta", "n", "attempts"]]

    # No starred 3-4 shot tier ships. Screened with the opening blinded and every figure
    # read off a fold that had no part in the selection, two of 1,752 three-shot
    # candidates survive, both for retired players who appear in no draw — see
    # experiments/rally_patterns. That experiment still runs weekly and still writes
    # reports/rally_patterns.csv, so this is where the tier would come back if the
    # charting ever funds one for a current player.

    # Opening cues by service court (shot_triggers' openings section). Same currency as
    # the pooled triggers above — a lead-up that shifts the player's aggressive shot
    # frequency — but scored against their own norm *for that shot and that court*, which
    # the pooled table cannot do: a wide serve opens a right-hander's forehand in the
    # deuce court and their backhand in the ad court, so the pooled row averages two
    # different serves and names neither. 310 of the pooled rows above are opening cues
    # shown that way; these are the same shots told properly.
    #
    # This waited until 2026-08-29 for a reason worth recording: the experiment produced
    # this table from the start, but as a raw threshold screen with no multiplicity
    # correction and its figures read off the data that selected them, while the pooled
    # table beside it was FDR-corrected and cross-validated. Shipping it in that state
    # would have put the panel's least-screened numbers next to its most-screened. It is
    # now on the same footing as everything else here.
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

    # ``sigma`` is not taken. It printed as the profile column's "shot selection" figure and
    # was cut by the test that retired the shot-quality score: it correlates -0.81 (men) /
    # -0.59 (women) with rally length, two thirds of the men's spread is the player's own
    # baseline aggressive shot frequency — which ``trig_att_rate`` below already carries in
    # plain percent — and its leaderboard was a serve-volley leaderboard, with Rafter falling
    # from the top of the tour to below the median once serve and net lead-ups came out. It
    # also carried no direction: it was independent of whether the extra aggression converted,
    # so one number described an adaptive player and a baited one identically.
    tp = pd.read_csv(REPORTS / "shot_triggers_players.csv")[
        ["player", "gender", "att_rate", "conversion", "n_traps"]].rename(
        columns={"att_rate": "trig_att_rate", "conversion": "trig_conversion"})
    summary = summary.merge(tp, on=["player", "gender"], how="left")

    # Serve placement (serve_tendencies experiment). Only the two targets that
    # survived that experiment's checks ship: the body share is partly a charter's
    # opinion (charters disagree about it by ±4-6% on the same players), so it is
    # measured there and deliberately not reported here. Shares are of all charted
    # first serves, so wide + T does not reach 100% — the remainder is the body.
    serve, serve_meta = _serve_placement()
    if serve is not None:
        bp = pd.read_csv(REPORTS / "serve_tendencies_leverage.csv")
        bp = bp[(bp.direction == "wide") & (bp.bucket == "break_pt")][
            ["player", "gender", "delta", "sig", "n"]].rename(
            columns={"delta": "serve_bp_wide_delta", "sig": "serve_bp_sig",
                     "n": "serve_bp_n"})
        summary = summary.merge(bp, on=["player", "gender"], how="left")

    meta = pd.DataFrame([{"key": f"mu_{g}", "value": round(v, 5)} for g, v in mu.items()]
                        + serve_meta)

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
