"""Filesystem layout for the project's data artifacts.

Two overrides, doing different jobs:

* ``MATCH_CHARTING_PROJECT_ROOT`` moves the whole checkout, ``reports/`` and ``docs/``
  included — every generated thing follows it.
* ``MATCH_CHARTING_PROJECT_DATA`` moves only ``data/``, which is the ~300 MB of raw CSVs,
  parquet and DuckDB files. That is the case ROOT cannot serve: the bulk on another volume
  with the repo where it is, and the figures and the site still written beside the code.

Every path under ``data/`` is built from ``DATA_DIR`` for that second override to hold —
the feed caches, the draw archive and the site's build artifacts as much as the corpus.
A module deriving its own ``PROJECT_ROOT / "data"`` would sit outside it silently.
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
