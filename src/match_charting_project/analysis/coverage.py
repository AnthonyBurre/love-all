"""Aggregations describing dataset coverage and charting cadence.

Every function takes a DuckDB connection and returns a tidy pandas DataFrame, so
they compose cleanly into notebooks, figures, or a future web API.
"""

import duckdb
import pandas as pd

from match_charting_project.analysis.tiers import TIER_ORDER
from match_charting_project.paths import DB_PATH


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DB_PATH), read_only=read_only)


def by_year(con) -> pd.DataFrame:
    """Matches charted per calendar year, split by gender."""
    return con.sql(
        """
        SELECT year, gender, COUNT(*) AS matches
        FROM matches WHERE year IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).df()


def by_tier(con) -> pd.DataFrame:
    """Matches charted per tier, split by gender (ordered high->low tier)."""
    df = con.sql(
        "SELECT tier, gender, COUNT(*) AS matches FROM matches GROUP BY 1, 2"
    ).df()
    df["tier"] = pd.Categorical(df["tier"], categories=TIER_ORDER, ordered=True)
    return df.sort_values(["tier", "gender"]).reset_index(drop=True)


def by_year_tier(con) -> pd.DataFrame:
    """Matches per year x tier (for stacked-area coverage charts)."""
    df = con.sql(
        """
        SELECT year, tier, COUNT(*) AS matches
        FROM matches WHERE year IS NOT NULL
        GROUP BY 1, 2 ORDER BY 1
        """
    ).df()
    df["tier"] = pd.Categorical(df["tier"], categories=TIER_ORDER, ordered=True)
    return df


def charting_activity(con, months: int = 36) -> pd.DataFrame:
    """Matches per month over the recent window (a proxy for charting cadence:
    recent matches are typically charted soon after they are played)."""
    return con.sql(
        f"""
        SELECT date_trunc('month', date) AS month, gender, COUNT(*) AS matches
        FROM matches
        WHERE date IS NOT NULL
          AND date >= (SELECT MAX(date) FROM matches) - INTERVAL '{months} months'
        GROUP BY 1, 2 ORDER BY 1, 2
        """
    ).df()


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
