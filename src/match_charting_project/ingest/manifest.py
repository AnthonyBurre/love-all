"""Provenance & freshness capture.

Answers "when did this data land?" at two granularities:

1. Per-file upstream freshness — the latest commit date that touched each source
   file in the MCP repo (the big files refresh in batches a few times a year).
2. Local ingestion runs — an append-only log of when *we* ingested and what the
   totals were, so charting cadence accrues over time.

All network calls are best-effort: failures are reported but never block a build.
"""

import json
from datetime import datetime, timezone

import pandas as pd
import requests

from match_charting_project.ingest.sources import REPO, all_sources
from match_charting_project.paths import PROCESSED_DIR, RAW_DIR, ensure_dirs

INGESTION_LOG = None  # set lazily to avoid import-time path binding


def _log_path():
    from match_charting_project.paths import DATA_DIR

    return DATA_DIR / "ingestion_log.jsonl"


def _last_commit_date(filename: str, session: requests.Session) -> str | None:
    url = f"https://api.github.com/repos/{REPO}/commits"
    try:
        resp = session.get(
            url, params={"path": filename, "per_page": 1}, timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            return data[0]["commit"]["committer"]["date"]
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None
    return None


def capture_source_manifest(what: str = "core") -> pd.DataFrame:
    """Build a manifest of source files with upstream + local freshness."""
    ensure_dirs()
    rows = []
    session = requests.Session()
    for src in all_sources(what):
        local = src.local_path
        rows.append(
            {
                "filename": src.filename,
                "category": src.category,
                "gender": src.gender.upper(),
                "key": src.key,
                "upstream_last_commit": _last_commit_date(src.filename, session),
                "local_bytes": local.stat().st_size if local.exists() else None,
                "downloaded": local.exists(),
            }
        )
    manifest = pd.DataFrame(rows)
    manifest["upstream_last_commit"] = pd.to_datetime(
        manifest["upstream_last_commit"], errors="coerce", utc=True
    )
    manifest.to_parquet(PROCESSED_DIR / "source_manifest.parquet", index=False)
    return manifest


def record_ingestion_run(n_matches: int, n_points: int, max_match_date) -> None:
    """Append one row to the local ingestion log (JSON Lines)."""
    ensure_dirs()
    record = {
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "n_matches": int(n_matches),
        "n_points": int(n_points),
        "max_match_date": (
            str(max_match_date) if max_match_date is not None else None
        ),
        "raw_bytes": sum(
            p.stat().st_size for p in RAW_DIR.glob("*.csv")
        ),
    }
    with open(_log_path(), "a") as fh:
        fh.write(json.dumps(record) + "\n")
