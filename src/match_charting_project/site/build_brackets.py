"""Assemble the servable site data: the live brackets feed + the insights db.

Writes ``docs/data/brackets.json`` (current draws, with each player tagged by their
matched Match Charting name) and copies ``insights.duckdb`` alongside it, so ``docs/``
can be served as-is. Both live under gitignored ``docs/data/`` — generated, never committed.
The fast CI path runs this; the slow path rebuilds ``insights.duckdb`` upstream.
"""

import json
import shutil
from datetime import datetime, timezone

from match_charting_project.analysis.coverage import connect
from match_charting_project.live import brackets, espn, players
from match_charting_project.paths import PROJECT_ROOT

DOCS_DATA = PROJECT_ROOT / "docs" / "data"


def _side(s, gender, universe) -> dict:
    matched = players.match_player(s.name, gender, universe) if s.name and s.name != "TBD" else None
    return {"name": s.name, "country": s.country, "winner": s.winner,
            "sets": s.sets, "matched": matched}


def payload() -> dict:
    tours = espn.current_tournaments()
    con = connect(read_only=True)
    universe = players.player_universe(con)
    con.close()
    out = {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
           "tournaments": []}
    for t in tours:
        out["tournaments"].append({
            "id": t.id, "name": t.name, "tier": t.tier, "gender": t.gender,
            "best_of": t.best_of,
            "rounds": [
                {"rank": r["rank"], "label": r["label"], "matches": [
                    {"id": m.id, "state": m.state, "detail": m.detail,
                     "a": _side(m.a, t.gender, universe), "b": _side(m.b, t.gender, universe)}
                    for m in r["matches"]]}
                for r in brackets.rounds(t)],
        })
    return out


def build() -> int:
    """Write docs/data/brackets.json (+ copy insights.duckdb). Returns tournament count."""
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    data = payload()
    (DOCS_DATA / "brackets.json").write_text(json.dumps(data))
    insights = PROJECT_ROOT / "data" / "insights.duckdb"
    if insights.exists():
        shutil.copy(insights, DOCS_DATA / "insights.duckdb")
    return len(data["tournaments"])
