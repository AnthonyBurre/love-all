"""The data feeds behind the site, and the caches that keep them off the git index.

Four feeds, each with its own cadence and its own source:

===========  ======================================  ==========================
feed         source                                  refresh
===========  ======================================  ==========================
calendar     Wikipedia season pages (tier, surface)  daily, when stale
draws        Wikipedia per-event draw pages          when a draw is published
scores       ESPN scoreboard (``live.espn``)         hourly
insights     Match Charting Project DB               weekly
===========  ======================================  ==========================

This module owns the first two. Both land in gitignored caches under ``data/`` that CI
carries as build assets — the same treatment ``history.json`` and ``insights.duckdb``
already get — so no draw sheet is ever committed to, or deleted from, the repository.

Two feeds come from Wikipedia, which is crowdsourced and so never trusted blindly:

* A parsed draw is only adopted once it *agrees with the live feed about who plays whom*
  (``wiki.feed_agreement``). A draw for the wrong event, the wrong gender, or last year's
  edition all parse perfectly well and all score near zero, so they're rejected and the
  bracket falls back to name inference — degraded, never wrong.
* The calendar decides which events the site serves at all. It replaced a hand-kept roster
  that, checked against it, had three events at the wrong level and was missing three more.
"""

import json
from datetime import date, datetime, timedelta, timezone

from match_charting_project.live import wiki
from match_charting_project.live.players import tourn_key
from match_charting_project.paths import PROJECT_ROOT

CALENDAR = PROJECT_ROOT / "data" / "calendar.json"
DRAWS = PROJECT_ROOT / "data" / "draws.json"

# A parsed draw must reproduce this share of the live feed's first-round pairings to be
# adopted. Set high: the right draw scores 1.0, and the nearest wrong answers score ≤0.06.
AGREEMENT_FLOOR = 0.9

# How long a calendar read stays good. A season page is *not* written once and left alone:
# it links each event's draw page only after that draw is made, so the page grows links all
# season. This used to be a season-equality check — refresh only when the cached season is
# last year's — and a cache taken on 2026-07-30, days before the National Bank Open draw was
# published, held all season with no draw link for it. Without the link the sheet is never
# fetched and the bracket stays unslotted, which would have gone on to cost every remaining
# event of the season: Cincinnati, the US Open, Shanghai, Paris, all of them.
CALENDAR_MAX_AGE = timedelta(days=1)

TOURS = {"M": "ATP", "W": "WTA"}
SOURCE_NOTE = "Draw sheets, tour levels and surfaces come from Wikipedia."


# --- cache I/O -------------------------------------------------------------------------

def _read(path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _write(path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1))


def load_calendar() -> dict:
    return _read(CALENDAR)


def load_draws() -> dict:
    return _read(DRAWS)


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="minutes")


# --- calendar --------------------------------------------------------------------------

def calendar_stale(cal: "dict | None" = None, now: "datetime | None" = None) -> bool:
    """True when the calendar cache is worth re-reading: missing, from another season, or
    older than ``CALENDAR_MAX_AGE``. An unreadable or undated cache counts as stale."""
    cal = load_calendar() if cal is None else cal
    if not cal.get("events") or cal.get("season") != date.today().year:
        return True
    try:
        fetched = datetime.fromisoformat(str(cal.get("fetched")))
    except ValueError:
        return True
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - fetched >= CALENDAR_MAX_AGE


def refresh_calendar_if_stale(season: "int | None" = None) -> "tuple[dict, bool]":
    """``(calendar, refreshed)`` — re-read the season pages only when the cache has aged
    out, so the hourly build costs two Wikipedia calls a day rather than two an hour."""
    cal = load_calendar()
    if not calendar_stale(cal):
        return cal, False
    return refresh_calendar(season), True


def refresh_calendar(season: "int | None" = None) -> dict:
    """Re-read both tours' season pages into the calendar cache. Returns the cache."""
    season = season or date.today().year
    doc = {"season": season, "fetched": _stamp(), "events": []}
    for gender, tour in TOURS.items():
        page = f"{season} {tour} Tour"
        idx = wiki.find_section(page, "Schedule")
        text = wiki.fetch_wikitext(page, section=idx) if idx is not None else None
        for ev in wiki.parse_calendar(text or ""):
            doc["events"].append({**ev, "gender": gender, "source_page": page})
    _write(CALENDAR, doc)
    return doc


def _candidates(cal: dict, gender: str, city: str, name: str,
                month: "int | None" = None) -> list:
    """Calendar events plausibly matching a live one, best first.

    The feed names events after sponsors ("Mubadala DC Open") and the calendar after their
    common name ("Washington Open"), so the venue city is the join. Cities are compared with
    containment either way because the two sides disagree on detail — "Washington" vs
    "Washington DC".

    The month is a *filter*, not a tie-breaker, and that matters more than it looks. The
    calendar covers 250 and up, so a WTA 125 is absent from it entirely — and the 125 played
    in Rome matches the Rome 1000 on city perfectly, which would put a 125 on the site as a
    1000. Requiring the weeks to line up separates them (May vs July). When either side has
    no month there is nothing to check, so the caller treats a multi-way result as unresolved.
    """
    ck, nk = tourn_key(city or ""), tourn_key(name or "")
    hits = []
    for ev in cal.get("events", []):
        if ev.get("gender") != gender:
            continue
        if month and ev.get("month") and abs(ev["month"] - month) > 1:
            continue                        # a different week is a different tournament
        ek = tourn_key(ev.get("city") or "")
        city_hit = bool(ck and ek and (ck in ek or ek in ck))
        name_hit = bool(nk and ev.get("event") and tourn_key(ev["event"]) in nk)
        if city_hit or name_hit:
            hits.append((0 if (city_hit and name_hit) else 1, ev))
    return [ev for _rank, ev in sorted(hits, key=lambda p: p[0])]


def lookup(city: str, name: str, gender: str, month: "int | None" = None,
           cal: "dict | None" = None) -> "dict | None":
    """The calendar entry for a live event, or None.

    ``month`` disambiguates a city hosting more than one event a season — Rome has a 1000 in
    May and a 125 in July. When several entries remain plausible the answer is *None*, not a
    guess: picking one would happily read the 125 as a 1000 and put it on the site. An
    unresolved event falls back to the name heuristics, which is a smaller error.
    """
    hits = _candidates(cal if cal is not None else load_calendar(),
                       gender, city, name, month)
    return hits[0] if len(hits) == 1 else None


# --- draws -----------------------------------------------------------------------------

def _draw_key(tournament) -> str:
    return f"{tourn_key(tournament.city or tournament.name)}|{tournament.gender}"


def _pages_for(tournament, cal: dict) -> "list[str]":
    """Draw pages worth trying for this event: whatever the calendar links for it."""
    month = None
    if getattr(tournament, "matches", None):
        stamps = [m.date for m in tournament.matches if getattr(m, "date", "")]
        if stamps:
            month = int(min(stamps)[5:7])
    ev = lookup(tournament.city or "", tournament.name, tournament.gender, month, cal)
    return list(ev.get("singles_pages") or []) if ev else []


def refresh_draws(tournaments: list, store: "dict | None" = None) -> dict:
    """Fetch and adopt any missing draw sheets for ``tournaments``.

    A draw is written to the cache only once it agrees with the live feed about first-round
    pairings, and an adopted draw is never re-fetched — a published draw doesn't change, and
    this keeps the hourly build to zero Wikipedia calls in the steady state.
    """
    store = load_draws() if store is None else store
    store.setdefault("draws", {})
    cal = load_calendar()
    for t in tournaments:
        key = _draw_key(t)
        if store["draws"].get(key, {}).get("r1"):
            continue
        for page in _pages_for(t, cal):
            text = wiki.fetch_wikitext(page)
            if not text:
                continue
            slots = wiki.parse_draw(text)
            if not wiki.is_usable(slots):
                continue
            agreement = wiki.feed_agreement(slots, t)
            if agreement < AGREEMENT_FLOOR:
                continue
            store["draws"][key] = {
                "tournament": t.name, "gender": t.gender, "city": t.city,
                "source_page": page, "source_url": wiki.page_url(page),
                "agreement": round(agreement, 3), "fetched": _stamp(),
                "r1": slots,
            }
            break
    store["updated"] = _stamp()
    _write(DRAWS, store)
    return store


def fixture_for(tournament, store: "dict | None" = None) -> "dict | None":
    """The cached draw for a live event in ``live.draws`` fixture shape, or None."""
    store = load_draws() if store is None else store
    rec = (store.get("draws") or {}).get(_draw_key(tournament))
    if not rec or not rec.get("r1"):
        return None
    return {"tournament": rec.get("tournament") or tournament.name,
            "gender": rec.get("gender") or tournament.gender,
            "source_url": rec.get("source_url"), "r1": rec["r1"]}
