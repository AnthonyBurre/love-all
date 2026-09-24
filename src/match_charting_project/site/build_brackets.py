"""Assemble the servable site data: the live brackets feed and the insights db.

Writes ``docs/data/brackets.json`` (live Grand Slam and 1000 draws from ESPN, plus the archive
of completed events in ``data/history.json``; see ``live.history``) and copies
``insights.duckdb`` beside it, so ``docs/`` serves as-is. Both are gitignored. The fast CI path
runs this; the slow path rebuilds ``insights.duckdb`` upstream.

Each player side is tagged with its matched charting name, and each match of a completed draw
with ``charted`` / ``chart_id`` once that event has any charting, re-derived from
``insights.duckdb`` every run.
"""

import json
import shutil
import sys
from datetime import datetime, timezone

import duckdb

from match_charting_project.live import brackets, draws, espn, feeds, history, players
from match_charting_project.paths import DATA_DIR, PROJECT_ROOT

DOCS_DATA = PROJECT_ROOT / "docs" / "data"
INSIGHTS = DATA_DIR / "insights.duckdb"
MATCH_DETAILS = DATA_DIR / "match_details"


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
            # Keyed on the *unordered* pair, because the draw and the chart name the same
            # meeting in either order. The chart's own player1 rides along in the value:
            # the per-match sidecar is written from that player's perspective, and the panel
            # has to know which of its two sides that is. Decided here rather than in the
            # browser so the comparison runs through the same normalize() that built the key.
            charted[(g, int(y), tk, frozenset((p1, p2)))] = (mid, p1)
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


def _chart_of(m: dict, gender: str, year: int, tks: "list[str]",
              charted: dict) -> "tuple[str, bool] | None":
    """This match's chart id, plus whether the chart's player1 is the draw's *B* side.

    The draw and the chart order a meeting independently — a draw slot is fixed by the
    bracket, a chart id by whoever filed it — so they disagree about which player comes
    first roughly half the time. Everything the sidecar holds is written player1-first,
    so the panel needs that flag to lay a match's own numbers against the right names.
    """
    a, b = m["a"]["name"], m["b"]["name"]
    if not a or not b or a == "TBD" or b == "TBD":
        return None
    na, nb = players.normalize(a), players.normalize(b)
    pair = frozenset((na, nb))
    for tk in tks:
        found = charted.get((gender, year, tk, pair))
        if found:
            mid, chart_p1 = found
            return mid, chart_p1 != na
    return None


def _backfill_event(t: dict, cal: dict) -> None:
    """Give an archived payload an ``event`` block if it lacks one, from the current calendar
    (a slam's name, level and surface don't change between seasons). An event the calendar
    doesn't list gets nothing.
    """
    if t.get("event"):
        return
    dates = [m["date"] for r in t["rounds"] for m in r["matches"] if m.get("date")]
    t["event"] = feeds.event_meta_for(
        t.get("city") or "", t.get("name") or "", t["gender"],
        int(min(dates)[5:7]) if dates else None, cal)


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
            m["charted"], m["chart_id"], m["chart_flip"] = None, None, None

    if not t.get("completed"):
        return
    tks = _tourn_keys(t)
    ids = {m["id"]: _chart_of(m, t["gender"], t["year"], tks, charted)
           for r in t["rounds"] for m in r["matches"]}
    if not any(ids.values()):             # nothing charted yet → per-player shading
        return
    for r in t["rounds"]:
        for m in r["matches"]:
            if m.get("placeholder"):
                continue
            found = ids[m["id"]]
            m["chart_id"] = found[0] if found else None
            m["chart_flip"] = found[1] if found else None
            m["charted"] = found is not None


def payload() -> dict:
    # Pick up newly published draw sheets first. The calendar comes first, since it links the
    # draw pages and sets each event's level. Adopted sheets aren't re-fetched and the calendar
    # only re-reads when stale, so a steady-state hourly run makes no Wikipedia calls. Both
    # reads degrade rather than fail, and say so on stderr so a degraded build is visible.
    try:
        feeds.refresh_calendar_if_stale()
    except Exception as exc:
        print(f"warning: Wikipedia calendar refresh failed ({type(exc).__name__}: {exc}); "
              "using the cached calendar", file=sys.stderr)
    tours = espn.current_tournaments()
    try:
        feeds.refresh_draws(tours)
    except Exception as exc:
        print(f"warning: Wikipedia draw refresh failed ({type(exc).__name__}: {exc}); "
              "draws fall back to name inference", file=sys.stderr)
    # How old the live scores actually are — the oldest of the two league fetches, so a
    # half-stale build dates itself by its worst half rather than its best.
    fetched_at = min((t.fetched_at for t in tours if t.fetched_at), default="")
    live = [brackets.serialize(t, use_fixture=True) for t in tours]

    store = history.load()
    history.archive(live, store)          # freeze any just-finished live draw
    history.prune(store)
    history.save(store)

    # Completed archive first, then any live draw not already frozen there.
    frozen = {(e["id"], e["gender"]) for e in store}
    tours = list(store) + [t for t in live if (t["id"], t["gender"]) not in frozen]

    universe, charted = _insights()
    cal = feeds.load_calendar()
    for t in tours:
        _backfill_event(t, cal)
        _annotate(t, universe, charted)
    # `updated` is the age of the *data*, not of the build. With no live draw there is no
    # live data to be stale about, so an all-archive build dates itself by the build.
    return {"updated": fetched_at or datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "tournaments": tours}


def _copy_match_details(data: dict) -> int:
    """Copy the per-match sidecar for every charted match these draws reference.

    The weekly build writes sidecars for every recent charted slam/1000 match; this serves
    only the ones the current draws can open, keeping ``docs/`` small. Rebuilt from scratch
    each run, so sidecars for pruned draws don't linger.
    """
    out = DOCS_DATA / "matches"
    if out.exists():
        shutil.rmtree(out)
    if not MATCH_DETAILS.is_dir():
        return 0
    wanted = {m["chart_id"] for t in data["tournaments"] for r in t["rounds"]
              for m in r["matches"] if m.get("chart_id")}
    out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for cid in wanted:
        src = MATCH_DETAILS / f"{cid}.json"
        if src.exists():
            shutil.copy(src, out / f"{cid}.json")
            copied += 1
    return copied


def build() -> "tuple[int, bool, int]":
    """Write docs/data/brackets.json (+ insights.duckdb, + the per-match sidecars).

    Returns (tournaments, insights copied, match sidecars copied).
    """
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    data = payload()
    (DOCS_DATA / "brackets.json").write_text(json.dumps(data))
    copied = INSIGHTS.exists()
    if copied:
        shutil.copy(INSIGHTS, DOCS_DATA / "insights.duckdb")
    return len(data["tournaments"]), copied, _copy_match_details(data)
