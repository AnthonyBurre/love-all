"""Normalize raw CSVs into typed parquet, then assemble a DuckDB database.

pandas does the messy column renaming / type coercion; parquet is the portable
on-disk format; DuckDB is the query layer built on top of the parquet files.
The matches table is enriched with derived columns (tournament tier, quality
flags) so downstream analysis can rely on them.
"""

import re

import duckdb
import pandas as pd

from match_charting_project.analysis.tiers import classify_tier
from match_charting_project.ingest import validate
from match_charting_project.ingest.sources import CORE_STATS, GENDERS, POINT_DECADES, STATS_DATASETS
from match_charting_project.paths import DB_PATH, PROCESSED_DIR, RAW_DIR, ensure_dirs

# Raw header -> snake_case. Anything not listed is slugified automatically, so
# this only needs the columns whose raw names are awkward or ambiguous.
MATCHES_RENAME = {
    "match_id": "match_id",
    "Player 1": "player1",
    "Player 2": "player2",
    "Pl 1 hand": "player1_hand",
    "Pl 2 hand": "player2_hand",
    "Date": "date",
    "Tournament": "tournament",
    "Round": "round",
    "Time": "time",
    "Court": "court",
    "Surface": "surface",
    "Umpire": "umpire",
    "Best of": "best_of",
    "Final TB?": "final_tb",
    "Charted by": "charted_by",
}

POINTS_RENAME = {
    "match_id": "match_id",
    "Pt": "pt",
    "Set1": "set1",
    "Set2": "set2",
    "Gm1": "gm1",
    "Gm2": "gm2",
    "Pts": "pts",
    "Gm#": "game_num",
    "TbSet": "tb_set",
    "TB?": "is_tb",
    "TBpt": "tb_pt",
    "Svr": "svr",
    "Ret": "ret",
    "Serving": "serving",
    "1st": "first_serve",
    "2nd": "second_serve",
    "Notes": "notes",
    "PtWinner": "pt_winner",
}

POINTS_INT_COLS = ["pt", "set1", "set2", "gm1", "gm2", "svr", "ret", "pt_winner"]
POINTS_BOOL_MAP = {"True": True, "False": False, "1": True, "0": False}


def _slug(name: str) -> str:
    slug = re.sub(r"[^\w]+", "_", str(name).strip().lower())
    return re.sub(r"_+", "_", slug).strip("_") or "col"


def _rename(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    return df.rename(columns={c: mapping.get(c, _slug(c)) for c in df.columns})


def build_matches() -> pd.DataFrame:
    frames = []
    for gender in GENDERS:
        path = RAW_DIR / f"charting-{gender}-matches.csv"
        if not path.exists():
            continue
        df = _rename(pd.read_csv(path, dtype=str), MATCHES_RENAME)
        df["gender"] = gender.upper()
        frames.append(df)
    matches = pd.concat(frames, ignore_index=True)
    matches["date"] = pd.to_datetime(matches["date"], format="%Y%m%d", errors="coerce")
    matches["year"] = matches["date"].dt.year.astype("Int64")
    if "best_of" in matches:
        matches["best_of"] = pd.to_numeric(matches["best_of"], errors="coerce").astype("Int64")
    matches["tier"] = [
        classify_tier(t, g) for t, g in zip(matches["tournament"], matches["gender"])
    ]
    matches = validate.flag_matches(matches)
    matches.to_parquet(PROCESSED_DIR / "matches.parquet", index=False)
    return matches


def build_points() -> pd.DataFrame:
    frames = []
    for gender in GENDERS:
        for decade in POINT_DECADES:
            path = RAW_DIR / f"charting-{gender}-points-{decade}.csv"
            if not path.exists():
                continue
            df = _rename(pd.read_csv(path, dtype=str), POINTS_RENAME)
            df["gender"] = gender.upper()
            df["decade"] = decade
            frames.append(df)
    points = pd.concat(frames, ignore_index=True)
    for col in POINTS_INT_COLS:
        if col in points:
            points[col] = pd.to_numeric(points[col], errors="coerce").astype("Int64")
    if "tb_set" in points:
        points["tb_set"] = points["tb_set"].map(POINTS_BOOL_MAP).astype("boolean")
    points.to_parquet(PROCESSED_DIR / "points.parquet", index=False)
    return points


def build_stats(which: str = "core") -> list[str]:
    names = STATS_DATASETS if which == "all" else CORE_STATS
    written = []
    for name in names:
        frames = []
        for gender in GENDERS:
            path = RAW_DIR / f"charting-{gender}-stats-{name}.csv"
            if not path.exists():
                continue
            df = pd.read_csv(path, dtype=str)
            df["gender"] = gender.upper()
            frames.append(df)
        if not frames:
            continue
        stats = pd.concat(frames, ignore_index=True)
        stats.to_parquet(PROCESSED_DIR / f"stats_{_slug(name)}.parquet", index=False)
        written.append(name)
    return written


def build_duckdb() -> list[str]:
    """Assemble the DuckDB database from every processed parquet (+ run log)."""
    from match_charting_project.paths import DATA_DIR

    DB_PATH.unlink(missing_ok=True)
    con = duckdb.connect(str(DB_PATH))
    tables = []
    for parquet in sorted(PROCESSED_DIR.glob("*.parquet")):
        table = parquet.stem
        con.execute(
            f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM read_parquet(?)',
            [str(parquet)],
        )
        tables.append(table)
    log = DATA_DIR / "ingestion_log.jsonl"
    if log.exists():
        con.execute(
            "CREATE OR REPLACE TABLE ingestion_runs AS "
            "SELECT * FROM read_json_auto(?)",
            [str(log)],
        )
        tables.append("ingestion_runs")
    con.close()
    return tables


def build_frames(stats_which: str = "core") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build & write the parquet frames and the data-quality report."""
    ensure_dirs()
    matches = build_matches()
    print(f"  matches : {len(matches):>9,} rows -> matches.parquet")
    points = build_points()
    print(f"  points  : {len(points):>9,} rows -> points.parquet")
    stats = build_stats(stats_which)
    print(f"  stats   : {', '.join(stats) if stats else 'none'}")

    m_rep = validate.matches_report(matches)
    p_rep = validate.points_report(points)
    from match_charting_project.paths import PROJECT_ROOT

    report_path = PROJECT_ROOT / "reports" / "data_quality.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(validate.render_markdown(m_rep, p_rep))
    print(
        f"  quality : {m_rep['invalid_surface']} bad surfaces, "
        f"{p_rep['duplicate_match_pt']} dup points -> reports/data_quality.md"
    )
    return matches, points


def build(stats_which: str = "core") -> pd.DataFrame:
    """Standalone build (no network): frames + DuckDB assembly."""
    matches, _ = build_frames(stats_which)
    tables = build_duckdb()
    print(f"  duckdb  : {len(tables)} tables -> {DB_PATH}")
    return matches
