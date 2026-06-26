"""Aggregations describing the dataset's true charting coverage.

Every function takes a DuckDB connection and returns a tidy pandas DataFrame, so
they compose cleanly into notebooks, figures, or a future web API.

"Coverage" here means charted / *played*, not a raw charted count, so every
metric needs a denominator we can pin down exactly without external results
data. A Grand Slam singles main draw is always 128 players = 127 matches (64 in
R128, 32 in R64, ... 1 final); Masters 1000 draws vary in size but always share
the same late rounds (R16=8 ... F=1). Both structures have held continuously
since 1990, which is why that is the floor year.
"""

import re

import duckdb
import pandas as pd

from match_charting_project.analysis.tiers import MASTERS_1000
from match_charting_project.paths import DB_PATH

# Grand Slam draw structure (singles main draw of 128 players).
SLAM_ROUND_SIZES = {"R128": 64, "R64": 32, "R32": 16, "R16": 8, "QF": 4, "SF": 2, "F": 1}
SLAM_MAIN_ROUNDS = tuple(SLAM_ROUND_SIZES)  # R128 -> F, draw order
SLAM_DRAW_MATCHES = sum(SLAM_ROUND_SIZES.values())  # 127
# Slams in calendar order, using the names as they appear in the data.
SLAMS = ("Australian Open", "Roland Garros", "Wimbledon", "US Open")
SLAM_SINCE = 1990  # all four slams have used a 128 draw continuously since 1990

_MAIN_SQL = ", ".join(f"'{r}'" for r in SLAM_MAIN_ROUNDS)

# Masters 1000 / WTA 1000 draws vary in size (56 / 96 / 128 across events and
# years), so there is no fixed full-draw denominator. The *late* rounds are
# invariant, though: every 1000-level draw has R16=8, QF=4, SF=2, F=1. We measure
# coverage against those 15 structurally-guaranteed matches.
MASTERS_LATE_SIZES = {"R16": 8, "QF": 4, "SF": 2, "F": 1}
MASTERS_LATE_ROUNDS = tuple(MASTERS_LATE_SIZES)  # R16 -> F
MASTERS_LATE_MATCHES = sum(MASTERS_LATE_SIZES.values())  # 15
MASTERS_SINCE = 1990  # ATP Masters Series began in 1990
_LATE_SQL = ", ".join(f"'{r}'" for r in MASTERS_LATE_ROUNDS)


def canon_masters_event(name: str) -> str:
    """Collapse a raw 1000-level tournament name to a stable event label.

    Handles the naming drift in the data: a trailing "Masters" tag, underscores
    for spaces, and the Montreal/Toronto alternation of the Canadian event.
    """
    s = re.sub(r"[_\s]+", " ", str(name)).strip()
    s = re.sub(r"\s*masters$", "", s, flags=re.IGNORECASE).strip()
    return {"Montreal": "Canada", "Toronto": "Canada"}.get(s, s)


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def summary(con) -> dict:
    """Headline coverage numbers for a report or dashboard."""
    row = con.sql(
        """
        SELECT
            COUNT(*)                         AS matches,
            COUNT(DISTINCT tournament)       AS tournaments,
            MIN(date)                        AS earliest,
            MAX(date)                        AS latest,
            SUM(CASE WHEN gender='M' THEN 1 ELSE 0 END) AS men,
            SUM(CASE WHEN gender='W' THEN 1 ELSE 0 END) AS women
        FROM matches
        """
    ).df().iloc[0]
    points = con.sql("SELECT COUNT(*) FROM points").fetchone()[0]
    classified = con.sql(
        "SELECT 100.0 * AVG(CASE WHEN tier <> 'Other / Unknown' "
        "THEN 1 ELSE 0 END) FROM matches"
    ).fetchone()[0]
    return {
        "matches": int(row["matches"]),
        "points": int(points),
        "men": int(row["men"]),
        "women": int(row["women"]),
        "tournaments": int(row["tournaments"]),
        "earliest": row["earliest"],
        "latest": row["latest"],
        "pct_tier_classified": round(float(classified), 1),
    }


def slam_coverage(con, since: int = SLAM_SINCE) -> pd.DataFrame:
    """True charting coverage of each Grand Slam singles draw.

    One row per (year, slam, gender) with `charted` main-draw matches and
    `coverage_pct` = charted / 127. Qualifying rounds are excluded so the
    numerator and the 127-match denominator describe the same population.
    """
    df = con.sql(
        f"""
        SELECT year, trim(tournament) AS slam, gender, COUNT(*) AS charted
        FROM matches
        WHERE tier = 'Grand Slam' AND round IN ({_MAIN_SQL})
          AND year >= {int(since)}
        GROUP BY 1, 2, 3
        """
    ).df()
    df["played"] = SLAM_DRAW_MATCHES
    df["coverage_pct"] = (100.0 * df["charted"] / SLAM_DRAW_MATCHES).clip(upper=100).round(1)
    df["slam"] = pd.Categorical(df["slam"], categories=SLAMS, ordered=True)
    return df.sort_values(["slam", "gender", "year"]).reset_index(drop=True)


def slam_round_completion(con, since: int = SLAM_SINCE) -> pd.DataFrame:
    """Completion rate per round across every slam draw in the data (>= `since`).

    For each round, `expected` = (number of slam draws present) x (matches that
    round holds in a full 128 draw), and `completion_pct` = charted / expected.
    This is what exposes the rich-get-charted pattern: finals are charted far
    more often than opening-round matches.
    """
    draws = con.sql(
        f"""
        SELECT gender,
               COUNT(DISTINCT year::VARCHAR || '|' || trim(tournament)) AS draws
        FROM matches
        WHERE tier = 'Grand Slam' AND round IN ({_MAIN_SQL}) AND year >= {int(since)}
        GROUP BY 1
        """
    ).df()
    charted = con.sql(
        f"""
        SELECT round, gender, COUNT(*) AS charted
        FROM matches
        WHERE tier = 'Grand Slam' AND round IN ({_MAIN_SQL}) AND year >= {int(since)}
        GROUP BY 1, 2
        """
    ).df()
    df = charted.merge(draws, on="gender", how="left")
    df["expected"] = df.apply(
        lambda r: SLAM_ROUND_SIZES[r["round"]] * r["draws"], axis=1
    )
    df["completion_pct"] = (100.0 * df["charted"] / df["expected"]).round(1)
    df["round"] = pd.Categorical(df["round"], categories=SLAM_MAIN_ROUNDS, ordered=True)
    return df.sort_values(["round", "gender"]).reset_index(drop=True)


def slam_round_coverage(con, since: int = SLAM_SINCE) -> pd.DataFrame:
    """Per-year completion of each Grand Slam round (for a round x year heatmap).

    One row per (year, gender, round). `expected` = (slam draws present that
    year) x (matches the round holds); `coverage_pct` = charted / expected.
    Every round is emitted for any year that has slam data, so a round nobody
    charted reads as 0% rather than a gap.
    """
    charted = con.sql(
        f"""
        SELECT year, gender, round, COUNT(*) AS charted
        FROM matches
        WHERE tier = 'Grand Slam' AND round IN ({_MAIN_SQL}) AND year >= {int(since)}
        GROUP BY 1, 2, 3
        """
    ).df()
    draws = con.sql(
        f"""
        SELECT year, gender, COUNT(DISTINCT trim(tournament)) AS draws
        FROM matches
        WHERE tier = 'Grand Slam' AND round IN ({_MAIN_SQL}) AND year >= {int(since)}
        GROUP BY 1, 2
        """
    ).df()
    return _round_grid(charted, draws, SLAM_ROUND_SIZES)


def masters_coverage(con, since: int = MASTERS_SINCE) -> pd.DataFrame:
    """Late-round (R16 onward) charting coverage of each 1000-level event.

    One row per (year, event, gender) with `charted` late-round matches and
    `coverage_pct` = charted / 15. Event names are canonicalized so the same
    tournament reads consistently across years. Unlike the slams this is *not*
    full-draw coverage — only the 15 rounds present in every draw size.
    """
    df = con.sql(
        f"""
        SELECT year, gender, trim(tournament) AS raw_event, COUNT(*) AS charted
        FROM matches
        WHERE tier = '{MASTERS_1000}' AND round IN ({_LATE_SQL})
          AND year >= {int(since)}
        GROUP BY 1, 2, 3
        """
    ).df()
    df["event"] = df["raw_event"].map(canon_masters_event)
    df = df.groupby(["year", "gender", "event"], as_index=False)["charted"].sum()
    df["played_late"] = MASTERS_LATE_MATCHES
    df["coverage_pct"] = (
        100.0 * df["charted"] / MASTERS_LATE_MATCHES
    ).clip(upper=100).round(1)
    return df.sort_values(["gender", "event", "year"]).reset_index(drop=True)


def masters_round_completion(con, since: int = MASTERS_SINCE) -> pd.DataFrame:
    """Late-round completion rate for 1000-level events, by round and gender.

    `expected` = (distinct event-draws present) x (matches that round holds), so
    `completion_pct` = charted / expected. Restricted to R16->F because earlier
    rounds vary with draw size and have no fixed denominator.
    """
    raw = con.sql(
        f"""
        SELECT year, gender, trim(tournament) AS raw_event, round, COUNT(*) AS charted
        FROM matches
        WHERE tier = '{MASTERS_1000}' AND round IN ({_LATE_SQL})
          AND year >= {int(since)}
        GROUP BY 1, 2, 3, 4
        """
    ).df()
    raw["event"] = raw["raw_event"].map(canon_masters_event)
    draws = (
        raw.groupby("gender")
        .apply(lambda g: g[["year", "event"]].drop_duplicates().shape[0], include_groups=False)
        .to_dict()
    )
    df = raw.groupby(["round", "gender"], as_index=False)["charted"].sum()
    df["draws"] = df["gender"].map(draws)
    df["expected"] = df.apply(
        lambda r: MASTERS_LATE_SIZES[r["round"]] * r["draws"], axis=1
    )
    df["completion_pct"] = (100.0 * df["charted"] / df["expected"]).round(1)
    df["round"] = pd.Categorical(df["round"], categories=MASTERS_LATE_ROUNDS, ordered=True)
    return df.sort_values(["round", "gender"]).reset_index(drop=True)


def masters_round_coverage(con, since: int = MASTERS_SINCE) -> pd.DataFrame:
    """Per-year completion of each 1000-level late round (round x year heatmap).

    Mirrors `slam_round_coverage` but over the invariant R16->F rounds, with
    canonicalized event names counted as the per-year draw denominator.
    """
    raw = con.sql(
        f"""
        SELECT year, gender, trim(tournament) AS raw_event, round, COUNT(*) AS charted
        FROM matches
        WHERE tier = '{MASTERS_1000}' AND round IN ({_LATE_SQL}) AND year >= {int(since)}
        GROUP BY 1, 2, 3, 4
        """
    ).df()
    raw["event"] = raw["raw_event"].map(canon_masters_event)
    charted = raw.groupby(["year", "gender", "round"], as_index=False)["charted"].sum()
    draws = (
        raw.groupby(["year", "gender"])["event"].nunique().rename("draws").reset_index()
    )
    return _round_grid(charted, draws, MASTERS_LATE_SIZES)


def _round_grid(charted: pd.DataFrame, draws: pd.DataFrame, sizes: dict) -> pd.DataFrame:
    """Build a dense (year, gender, round) coverage grid from charted + draws.

    `charted` has columns year/gender/round/charted (sparse); `draws` has the
    per-(year, gender) draw count; `sizes` maps round -> matches in a full draw.
    Rounds missing from `charted` are filled with 0 so they render as 0%, while
    year-genders absent from `draws` simply do not appear (rendered as gaps).
    """
    rounds = list(sizes)
    grid = draws.merge(pd.DataFrame({"round": rounds}), how="cross")
    grid = grid.merge(charted, on=["year", "gender", "round"], how="left")
    grid["charted"] = grid["charted"].fillna(0).astype(int)
    grid["expected"] = grid["round"].map(sizes) * grid["draws"]
    grid["coverage_pct"] = (
        100.0 * grid["charted"] / grid["expected"]
    ).clip(upper=100).round(1)
    grid["round"] = pd.Categorical(grid["round"], categories=rounds, ordered=True)
    return grid.sort_values(["gender", "round", "year"]).reset_index(drop=True)


def freshness(con) -> pd.DataFrame:
    """Per-file upstream freshness, if the source manifest table exists."""
    tables = {t[0] for t in con.sql("SHOW TABLES").fetchall()}
    if "source_manifest" not in tables:
        return pd.DataFrame()
    return con.sql(
        """
        SELECT category, gender, filename, upstream_last_commit, local_bytes
        FROM source_manifest
        ORDER BY upstream_last_commit DESC NULLS LAST
        """
    ).df()
