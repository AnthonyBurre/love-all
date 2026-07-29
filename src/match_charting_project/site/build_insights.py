"""Build the compact ``insights.duckdb`` the Pages site queries in-browser via DuckDB-WASM.

A small projection of the main DB — one row per charted player — assembled from the
experiment CSVs + the graduated library, keyed by **base player name** (era-split
entities are collapsed to their most recent era = current form). Aggregates only, so it
stays small enough to ship; nothing is committed (it lands under gitignored ``data/``).

Prereq: the experiments have been run so their CSVs exist in ``reports/`` (the CI
insights workflow runs them first). Run: ``match-charting-project site build-insights``.
"""

import re
from datetime import date

import duckdb
import pandas as pd

from match_charting_project.live.players import coverage, normalize, tourn_key
from match_charting_project.paths import DB_PATH, PROJECT_ROOT
from match_charting_project.winprob_match import current_strength

REPORTS = PROJECT_ROOT / "reports"
OUT = PROJECT_ROOT / "data" / "insights.duckdb"
_ERA_RE = re.compile(r"^(?P<base>.+) \((?P<y0>\d{4})[–-](?P<y1>\d{4})\)$")
# Only recent slam/1000 identities ship: the site archives completed events going forward,
# never older ones, so their per-match charting status is all the fast path can ever need.
_CHARTED_SINCE = date.today().year - 2


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


def build() -> int:
    """(Re)create ``insights.duckdb`` from the DB + experiment CSVs. Returns player count."""
    con = duckdb.connect(str(DB_PATH), read_only=True)
    strength, mu = current_strength(con)
    cov = coverage(con)
    charted = _charted_matches(con)
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

    lang = pd.read_csv(REPORTS / "shot_language_players.csv")[["player", "gender", "bits"]]
    summary = summary.merge(lang, on=["player", "gender"], how="left")

    # Court-state response profiles (court_response experiment): the player's stable,
    # hand-normalized answers to a given incoming ball, plus the return-depth family.
    # These replaced the old signature pairs, which mostly surfaced generic rally
    # geometry and handedness artifacts — see experiments/court_response.
    patterns = pd.read_csv(REPORTS / "court_response_players.csv")[
        ["player", "gender", "family", "state", "response", "state_depth",
         "inc_code", "resp_code", "lift", "count", "n_state", "evidence",
         "win_rate", "tour_win_rate"]]
    for col in ("inc_code", "resp_code"):
        patterns[col] = patterns[col].astype(str)
    patterns["state_depth"] = patterns["state_depth"].fillna("")

    crw = _collapse(pd.read_csv(REPORTS / "class_relative_wpa.csv")
                    [["player", "gender", "class_rel_z", "accuracy", "avg_wpa_lost"]])
    summary = summary.merge(crw, on=["player", "gender"], how="left")

    # Shot-making triggers (shot_triggers experiment): green lights by attempt lift,
    # traps by how far conversion falls below the player's norm. (These superseded the
    # old separate winner/error pattern books — see experiments/shot_triggers.)
    tr = pd.read_csv(REPORTS / "shot_triggers.csv")
    greens = (tr[tr.tag == "green"].sort_values("att_lift", ascending=False)
              .groupby(["player", "gender"]).head(3))
    traps = (tr[tr.tag == "trap"].sort_values("conv_delta")
             .groupby(["player", "gender"]).head(3))
    triggers = pd.concat([greens, traps])[
        ["player", "gender", "tag", "context", "att_rate", "att_lift",
         "conversion", "conv_delta", "n"]]
    triggers["depth"] = 2

    # Gold-star deep patterns (deep_patterns experiment): 3-4 shot sequences that
    # beat their own shorter parent and replicate — only the hugely-charted have them.
    # att_lift for these rows is the lift vs the parent pattern, not vs base rate.
    dp_path = REPORTS / "deep_patterns.csv"
    if dp_path.exists():
        dp = pd.read_csv(dp_path).rename(columns={"parent_lift": "att_lift"})
        deep = (dp.sort_values("att_lift", ascending=False)
                .groupby(["player", "gender"]).head(3))
        triggers = pd.concat([triggers, deep[triggers.columns]])

    tp = pd.read_csv(REPORTS / "shot_triggers_players.csv")[
        ["player", "gender", "att_rate", "conversion", "sigma", "n_traps"]].rename(
        columns={"att_rate": "trig_att_rate", "conversion": "trig_conversion"})
    summary = summary.merge(tp, on=["player", "gender"], how="left")

    meta = pd.DataFrame([{"key": f"mu_{g}", "value": round(v, 5)} for g, v in mu.items()])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.unlink(missing_ok=True)     # fresh file: dropped tables must not ship forever
    out = duckdb.connect(str(OUT))
    for name, df in (("player_summary", summary), ("player_triggers", triggers),
                     ("player_patterns", patterns), ("meta", meta),
                     ("charted_matches", charted)):
        out.register(f"_{name}", df)
        out.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM _{name}")
    out.close()
    return len(summary)
