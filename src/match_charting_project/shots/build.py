"""Materialize decoded points into a queryable ``points_parsed`` table.

Parsing the shot notation is the new primitive the repo lacked. Rather than have
every analysis re-decode 1.85M strings, this writes one tidy per-point row (rally
length, outcome, ending wing/kind, server_won) to parquet and registers it as a
DuckDB table, so downstream work joins ``points_parsed`` to ``points`` / ``matches``.
"""

import duckdb
import pandas as pd

from match_charting_project.paths import DB_PATH, PROCESSED_DIR
from match_charting_project.shots.notation import parse_point, point_features

# match_id/pt key + everything parse_point needs + gender (handy for filtering).
_SOURCE_SQL = (
    "SELECT match_id, pt, gender, svr, first_serve, second_serve, pt_winner FROM points"
)


def build_parsed_points(chunk: int = 200_000) -> int:
    """Decode every point and (re)create the ``points_parsed`` parquet + table."""
    if not DB_PATH.exists():
        raise FileNotFoundError(f"No database at {DB_PATH}. Run: match-charting-project ingest")

    con = duckdb.connect(str(DB_PATH))
    cursor = con.execute(_SOURCE_SQL)
    rows: list[dict] = []
    while True:
        batch = cursor.fetchmany(chunk)
        if not batch:
            break
        for match_id, pt, gender, svr, fs, ss, win in batch:
            feat = point_features(parse_point(fs, ss, svr, win), match_id=match_id, pt=pt)
            feat["gender"] = gender
            rows.append(feat)

    df = pd.DataFrame(rows)
    out = PROCESSED_DIR / "points_parsed.parquet"
    df.to_parquet(out, index=False)
    con.execute(
        "CREATE OR REPLACE TABLE points_parsed AS SELECT * FROM read_parquet(?)",
        [str(out)],
    )
    con.close()
    return len(df)
