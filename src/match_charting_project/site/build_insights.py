"""Build the compact ``insights.duckdb`` the Pages site queries in-browser via DuckDB-WASM.

A small projection of the main DB — one row per charted player — assembled from the
experiment CSVs + the graduated library, keyed by **base player name** (era-split
entities are collapsed to their most recent era = current form). Aggregates only, so it
stays small enough to ship; nothing is committed (it lands under gitignored ``data/``).

Prereq: the experiments have been run so their CSVs exist in ``reports/`` (the CI
insights workflow runs them first). Run: ``match-charting-project site build-insights``.
"""

import re

import duckdb
import pandas as pd

from match_charting_project.live.players import coverage
from match_charting_project.paths import DB_PATH, PROJECT_ROOT
from match_charting_project.winprob_match import current_strength

REPORTS = PROJECT_ROOT / "reports"
OUT = PROJECT_ROOT / "data" / "insights.duckdb"
_ERA_RE = re.compile(r"^(?P<base>.+) \((?P<y0>\d{4})[–-](?P<y1>\d{4})\)$")


def _base(entity: str) -> "tuple[str, int]":
    m = _ERA_RE.match(str(entity))
    return (m["base"], int(m["y1"])) if m else (str(entity), 0)


def _collapse(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse era entities to base names, keeping the latest era per (gender, player)."""
    df = df.copy()
    parsed = [_base(p) for p in df["player"]]
    df["player"] = [b for b, _ in parsed]
    df["_y1"] = [y for _, y in parsed]
    return df.sort_values("_y1").groupby(["gender", "player"], as_index=False).last().drop(
        columns="_y1")


def build() -> int:
    """(Re)create ``insights.duckdb`` from the DB + experiment CSVs. Returns player count."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    strength, mu = current_strength(con)
    cov = coverage(con)
    con.close()

    summary = pd.DataFrame([
        {"gender": g, "player": p, "serve_rate": round(sv, 4), "return_rate": round(rt, 4),
         "matches_charted": cov.get((g, p), {}).get("matches", 0),
         "points_charted": cov.get((g, p), {}).get("points", 0)}
        for (g, p), (sv, rt) in strength.items()
    ])

    clusters = _collapse(pd.read_csv(REPORTS / "player_style_clusters.csv")
                         [["player", "gender", "archetype"]])
    summary = summary.merge(clusters, on=["player", "gender"], how="left")

    lang = pd.read_csv(REPORTS / "shot_language_players.csv")[
        ["player", "gender", "bits", "signatures"]]
    summary = summary.merge(lang, on=["player", "gender"], how="left")

    crw = _collapse(pd.read_csv(REPORTS / "class_relative_wpa.csv")
                    [["player", "gender", "class_rel_z", "accuracy", "avg_wpa_lost"]])
    summary = summary.merge(crw, on=["player", "gender"], how="left")

    sp = pd.read_csv(REPORTS / "shot_patterns.csv")
    sp["kind"] = sp["outcome"].map({"winner": "green", "unforced_error": "trouble"})
    patterns = (sp.sort_values("rate", ascending=False)
                .groupby(["player", "gender", "kind"]).head(4)
                [["player", "gender", "kind", "context", "rate", "lift", "n"]])

    meta = pd.DataFrame([{"key": f"mu_{g}", "value": round(v, 5)} for g, v in mu.items()])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = duckdb.connect(str(OUT))
    for name, df in (("player_summary", summary), ("player_patterns", patterns), ("meta", meta)):
        out.register(f"_{name}", df)
        out.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _{name}")
    out.close()
    return len(summary)
