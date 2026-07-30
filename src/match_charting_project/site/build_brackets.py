"""Assemble the servable site data: the live brackets feed + the insights db.

Writes ``docs/data/brackets.json`` — live Grand Slam / 1000 draws from ESPN plus the
accumulating archive of completed events (``data/history.json``, see ``live.history``) — and
copies ``insights.duckdb`` alongside it, so ``docs/`` can serve as-is. Both live under
gitignored ``docs/data/`` — generated, never committed. The fast CI path runs this; the slow
path rebuilds ``insights.duckdb`` upstream.

Each player side is tagged with its matched Match-Charting name; each match of a *completed*
draw is tagged ``charted`` / ``chart_id`` (its Tennis Abstract chart) once that event has any
charting — both re-derived from ``insights.duckdb`` every run, so nothing goes stale.
"""

import json
import shutil
from datetime import datetime, timezone

import duckdb

from match_charting_project.live import brackets, draws, espn, feeds, history, players
from match_charting_project.paths import PROJECT_ROOT

DOCS_DATA = PROJECT_ROOT / "docs" / "data"
INSIGHTS = PROJECT_ROOT / "data" / "insights.duckdb"


def _insights() -> "tuple[dict, dict]":
    """From insights.duckdb: the player universe and the charted-match lookup. Empty when
    the db is absent (fast path with no release yet) — everything then reads as uncharted."""
    if not INSIGHTS.exists():
        return {"M": {}, "W": {}}, {}
    con = duckdb.connect(str(INSIGHTS), read_only=True)
    universe = players.universe_from_rows(
        con.execute("SELECT gender, player FROM player_summary").fetchall())
    charted = {}
    try:
        for g, y, tk, p1, p2, mid in con.execute(
                "SELECT gender, year, tourn_key, p1_norm, p2_norm, match_id "
                "FROM charted_matches").fetchall():
            charted[(g, int(y), tk, frozenset((p1, p2)))] = mid
    except duckdb.CatalogException:
        pass                              # older insights db without the table
    con.close()
    return universe, charted


def _tourn_keys(t: dict) -> "list[str]":
    """The db keys this tournament might be filed under: its venue city and its feed name.

    The charted db names events by city; the feed names them by sponsor, and the two only
    coincide for the slams ('Wimbledon') — where the city is the *wrong* answer ('London').
    Rather than branch on tier, try both: the rest of the lookup key is gender + year +
    both players, so a spurious second key can't collide with anything real.
    """
    return list(dict.fromkeys(
        players.tourn_key(v) for v in (t.get("city"), t.get("name")) if v))


def _chart_id(m: dict, gender: str, year: int, tks: "list[str]", charted: dict) -> "str | None":
    a, b = m["a"]["name"], m["b"]["name"]
    if not a or not b or a == "TBD" or b == "TBD":
        return None
    pair = frozenset((players.normalize(a), players.normalize(b)))
    for tk in tks:
        found = charted.get((gender, year, tk, pair))
        if found:
            return found
    return None


def _annotate(t: dict, universe: dict, charted: dict) -> None:
    """Tag sides with their matched charting name; tag a completed draw's matches with
    charted/chart_id — but only once the event has any charting, else leave them null so
    the site keeps per-player shading for a not-yet-touched draw."""
    for r in t["rounds"]:
        for m in r["matches"]:
            for s in (m["a"], m["b"]):
                # "Bye" is a slot marker, not an entrant — never send it through the fuzzy
                # player match, which would happily find a near-namesake for it.
                named = s["name"] and s["name"] not in ("TBD", draws.BYE)
                s["matched"] = (players.match_player(s["name"], t["gender"], universe)
                                if named else None)
            m["charted"], m["chart_id"] = None, None

    if not t.get("completed"):
        return
    tks = _tourn_keys(t)
    ids = {m["id"]: _chart_id(m, t["gender"], t["year"], tks, charted)
           for r in t["rounds"] for m in r["matches"]}
    if not any(ids.values()):             # nothing charted yet → per-player shading
        return
    for r in t["rounds"]:
        for m in r["matches"]:
            if m.get("placeholder"):
                continue
            m["chart_id"] = ids[m["id"]]
            m["charted"] = ids[m["id"]] is not None


def payload() -> dict:
    # Pick up any newly-published draw sheet before serializing, so a draw released since the
    # last run is scaffolded on this one. Adopted sheets are never re-fetched, so the steady
    # state costs no Wikipedia calls.
    tours = espn.current_tournaments()
    try:
        feeds.refresh_draws(tours)
    except Exception:
        pass                              # a draw feed outage degrades to name inference
    live = [brackets.serialize(t, use_fixture=True) for t in tours]

    store = history.load()
    history.archive(live, store)          # freeze any just-finished live draw
    history.prune(store)
    history.save(store)

    # Completed archive first, then any live draw not already frozen there.
    frozen = {(e["id"], e["gender"]) for e in store}
    tours = list(store) + [t for t in live if (t["id"], t["gender"]) not in frozen]

    universe, charted = _insights()
    for t in tours:
        _annotate(t, universe, charted)
    return {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "tournaments": tours}


def build() -> "tuple[int, bool]":
    """Write docs/data/brackets.json (+ copy insights.duckdb). Returns (tournaments, copied)."""
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    data = payload()
    (DOCS_DATA / "brackets.json").write_text(json.dumps(data))
    copied = INSIGHTS.exists()
    if copied:
        shutil.copy(INSIGHTS, DOCS_DATA / "insights.duckdb")
    return len(data["tournaments"]), copied
