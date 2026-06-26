"""Filesystem layout for the project's data artifacts.

Override locations with the MATCH_CHARTING_PROJECT_ROOT or MATCH_CHARTING_PROJECT_DATA env vars.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(
    os.environ.get("MATCH_CHARTING_PROJECT_ROOT", Path(__file__).resolve().parents[2])
)
DATA_DIR = Path(os.environ.get("MATCH_CHARTING_PROJECT_DATA", PROJECT_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DB_PATH = DATA_DIR / "tennis.duckdb"


def ensure_dirs() -> None:
    for directory in (RAW_DIR, PROCESSED_DIR):
        directory.mkdir(parents=True, exist_ok=True)
