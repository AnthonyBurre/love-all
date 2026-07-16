"""The accumulating archive of completed draws — so the site has something to show
between events, and every finished match becomes an entry point into the charting project.

Two ways in, one store:
  * ``archive()`` freezes a tournament the moment its final is decided in the live ESPN
    feed we already fetch — no extra requests, and the snapshot never changes afterwards.
  * ``harvest()`` seeds a past event once, by merging ESPN's *dated* scoreboards across the
    event's days (the live feed only carries what's current). This is the only path that
    reaches back before the site was watching; every event after is caught by ``archive()``.

The store (``data/history.json``) holds serialized tournament payloads (``brackets.serialize``
shape) plus ``year``/``season``/``completed``/``archived_at``. It is structural only — the
DB-derived ``matched``/``charted`` annotation is re-applied fresh by ``build_brackets`` each
run, so charting that lands after archival still shows up. Retention (``prune``) keeps the
last two years of slams plus the single most-recent event of any tier.
"""

import copy
import json
import urllib.request
from datetime import date, datetime, timedelta, timezone

from match_charting_project.live import brackets, espn
from match_charting_project.paths import PROJECT_ROOT

HISTORY = PROJECT_ROOT / "data" / "history.json"
_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/tennis/{league}/scoreboard?dates={d}"
# Generous main-draw windows (month/day) per slam, so a single seed sweep catches every
# round through the final regardless of the year's exact scheduling.
_SLAM_WINDOWS = {
    "australian open": ((1, 1), (2, 5)),
    "roland garros": ((5, 18), (6, 12)),
    "wimbledon": ((6, 24), (7, 16)),
    "us open": ((8, 20), (9, 12)),
}


# --- store I/O -------------------------------------------------------------------------

def load() -> list:
    if HISTORY.exists():
        return json.loads(HISTORY.read_text())
    return []


def save(store: list) -> None:
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(store))


# --- completion + accumulation ---------------------------------------------------------

def is_complete(rounds: list) -> bool:
    """A draw is done once its final (the last round's lone match) is played with a winner."""
    if not rounds or not rounds[-1].get("matches"):
        return False
    m = rounds[-1]["matches"][0]
    return m.get("state") == "post" and bool(m["a"].get("winner") or m["b"].get("winner"))


def _stamp(payload: dict, year: int) -> dict:
    frozen = copy.deepcopy(payload)
    frozen["completed"] = True
    frozen["year"] = year
    frozen["season"] = year
    frozen["archived_at"] = datetime.now(timezone.utc).isoformat(timespec="minutes")
    return frozen


def archive(live_payloads: list, store: list, today: "date | None" = None) -> int:
    """Freeze any newly-completed live tournament into ``store`` (once — never overwrite a
    frozen snapshot). Returns how many were added. ``live_payloads`` are ``serialize`` dicts.
    """
    today = today or date.today()
    have = {(e["id"], e["gender"]) for e in store}
    added = 0
    for t in live_payloads:
        if (t["id"], t["gender"]) in have or not is_complete(t["rounds"]):
            continue
        store.append(_stamp(t, today.year))
        have.add((t["id"], t["gender"]))
        added += 1
    return added


def prune(store: list, today: "date | None" = None) -> list:
    """Keep slams from the last two years plus the single most-recently-archived event;
    drop the rest. Mutates and returns ``store``."""
    today = today or date.today()
    keep_ids = set()
    for e in store:
        if "grand slam" in (e.get("tier") or "").lower() and e.get("year", 0) >= today.year - 2:
            keep_ids.add((e["id"], e["gender"]))
    if store:
        newest = max(store, key=lambda e: e.get("archived_at", ""))
        keep_ids.add((newest["id"], newest["gender"]))
    store[:] = [e for e in store if (e["id"], e["gender"]) in keep_ids]
    return store


# --- one-time seed from ESPN's dated feed ----------------------------------------------

def _fetch(league: str, day: str) -> dict:
    url = _SCOREBOARD.format(league=league, d=day)
    req = urllib.request.Request(url, headers={"User-Agent": "match-charting-project"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def recent_slams(today: "date | None" = None) -> "list[tuple[str, int]]":
    """(event, year) for slams whose main draw has begun as of ``today``, most-recent start
    first. The one-time seed walks this and archives the first that harvests *complete*, so a
    slam still in progress falls through to the one before it — no hardcoded final dates."""
    today = today or date.today()
    out = []
    for name, ((sm, sd), _end) in _SLAM_WINDOWS.items():
        for yr in (today.year, today.year - 1, today.year - 2):
            start = date(yr, sm, sd)
            if start <= today:
                out.append((start, name, yr))
    out.sort(reverse=True)
    return [(name, yr) for _s, name, yr in out]


def _window(event: str, year: int) -> "list[str]":
    from match_charting_project.live.players import tourn_key

    win = _SLAM_WINDOWS.get(tourn_key(event))
    if not win:
        raise ValueError(
            f"No date window known for '{event}'. Harvest supports the four slams; other "
            "events are caught automatically once they finish in the live feed.")
    (m0, d0), (m1, d1) = win
    start, end = date(year, m0, d0), date(year, m1, d1)
    return [(start + timedelta(days=i)).strftime("%Y%m%d")
            for i in range((end - start).days + 1)]


def harvest(event: str, year: int) -> "list[dict]":
    """Seed one past event: merge ESPN's dated scoreboards across its window into complete
    per-gender draws. Returns stamped ``serialize`` payloads (one per gender present)."""
    # (event_id, slug) -> {competition_id: raw competition}, plus each event's meta.
    buckets: dict = {}
    meta: dict = {}
    from match_charting_project.live.players import tourn_key
    want = tourn_key(event)
    for day in _window(event, year):
        for league in ("atp", "wta"):
            try:
                raw = _fetch(league, day)
            except Exception:
                continue
            for ev in raw.get("events", []):
                if want not in tourn_key(ev.get("name", "")):
                    continue
                eid = str(ev.get("id"))
                meta[eid] = {"id": eid, "name": ev.get("name", ""), "major": ev.get("major")}
                for g in ev.get("groupings", []):
                    slug = (g.get("grouping") or {}).get("slug")
                    if slug not in ("mens-singles", "womens-singles"):
                        continue
                    b = buckets.setdefault((eid, slug), {})
                    for c in g.get("competitions", []):
                        b[str(c.get("id"))] = c        # later day wins → final states

    # Re-wrap the merged competitions as a synthetic scoreboard and reuse espn.parse.
    events = []
    for eid, m in meta.items():
        groupings = [{"grouping": {"slug": slug}, "competitions": list(comps.values())}
                     for (e2, slug), comps in buckets.items() if e2 == eid]
        if groupings:
            events.append({**m, "groupings": groupings})
    tours = espn.parse({"events": events})
    return [_stamp(brackets.serialize(t, use_fixture=False), year) for t in tours]
