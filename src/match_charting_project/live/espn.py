"""ESPN's unofficial tennis JSON API — the swappable live source adapter.

All ESPN-specific JSON shapes are confined to this module; everything downstream
consumes the neutral ``Tournament`` / ``Match`` / ``Side`` dataclasses, so a paid feed
could replace it without touching the site. Free, no key, near-real-time — but
unofficial, so we cache the last successful raw JSON and fall back to it on failure.

Shape (verified against the live endpoint):
  events[]            → a tournament (``major`` flags a Grand Slam; ``venue`` gives the city)
    groupings[]       → a draw; ``grouping.slug`` = mens-singles / womens-singles / …
      competitions[]  → a match: ``round.displayName``, ``status.type.state``, competitors[]
        competitors[] → ``athlete.displayName`` / ``flag.alt`` / ``winner`` / ``linescores[]``
"""

import json
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from match_charting_project.analysis.tiers import (
    CITIES_1000,
    GRAND_SLAM,
    MASTERS_1000,
    classify_tier,
)
from match_charting_project.live import UA, feeds, levels
from match_charting_project.paths import PROJECT_ROOT

_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/tennis/{league}/scoreboard"
_CACHE = PROJECT_ROOT / "data" / "live"
_FETCHED_AT = "_fetched_at"     # our key, added to the cached copy only — not ESPN's shape
# Scores only move while a draw is being played, so that is the only time we poll on the
# hourly schedule. Off-week the cache is served untouched and one probe a day is enough to
# notice the next event — a request budget that tracks the tour rather than the clock.
_PROBE = timedelta(days=1)
# Keep polling this far past an event's end so the final lands in the archive, and this far
# before its start so a draw published early is picked up.
_GRACE = timedelta(days=1)
_SINGLES = {"mens-singles": "M", "womens-singles": "W"}
_TARGET_TIERS = (GRAND_SLAM, MASTERS_1000, levels.TOUR_500)
# Round display-name -> sortable rank (main draw only; qualifying excluded).
_ROUND_NAMED = {"final": 100, "semifinal": 99, "semifinals": 99,
                "quarterfinal": 98, "quarterfinals": 98,
                "round of 16": 4, "round of 32": 3, "round of 64": 2, "round of 128": 1}


@dataclass
class Side:
    name: str
    country: "str | None"
    winner: bool
    sets: list          # per-set games won (linescores)
    # Per-set outcome as the feed reports it: True where this side took the set, False
    # where it lost it, None where the set isn't decided (in progress, or suspended
    # mid-set). Parallel to `sets`. The site bolds a set score only where this is True,
    # so a suspended match's live set doesn't read as won by whoever's ahead in it.
    set_wins: list = field(default_factory=list)


@dataclass
class Match:
    id: str
    round_rank: int     # sortable (1 = first main-draw round … 100 = final)
    round_label: str    # "Round 1", "Quarterfinal", …
    state: str          # pre | in | post
    detail: str         # ESPN shortDetail (time, live score, or "Final")
    a: Side
    b: Side
    date: str = ""      # ISO scheduled/played datetime, e.g. "2026-07-06T09:05Z"


@dataclass
class Tournament:
    id: str
    name: str
    tier: str
    gender: str         # M | W
    best_of: int
    matches: list
    city: str = ""      # venue city — how the charted db names tournaments, unlike the feed
    fetched_at: str = ""  # ISO minute this draw's scoreboard actually came off the wire


def _iso(value: "str | None") -> "datetime | None":
    try:
        when = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _playing(raw: dict, now: datetime) -> bool:
    """Is a draw in this scoreboard being played (within the grace margin) right now?

    Read off the *cached* copy, which is the only thing we know without spending a request.
    Every uncertainty resolves to True: no cache, no events, unparseable dates. A gate that
    guesses wrong in the open direction costs one request; guessing wrong the other way
    takes the site dark for a tournament.
    """
    windows = [(_iso(e.get("date")), _iso(e.get("endDate"))) for e in raw.get("events", [])]
    windows = [(s, e) for s, e in windows if s and e]
    if not windows:
        return True
    return any(s - _GRACE <= now <= e + _GRACE for s, e in windows)


def _cached_copy(path) -> "tuple[dict, str] | None":
    """Our stored scoreboard and the stamp we wrote on it, or None if there isn't one."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
    except ValueError:
        return None
    stamp = raw.pop(_FETCHED_AT, "") or datetime.fromtimestamp(
        path.stat().st_mtime, timezone.utc).isoformat(timespec="minutes")
    return raw, stamp


def _fetch(league: str, now: "datetime | None" = None) -> "tuple[dict, str]":
    """Scoreboard JSON, plus the ISO minute it actually came off the wire.

    That second value is what the site dates itself by. Stamping the *build* time instead
    would date a cache fallback as though it were fresh — the one failure mode that looks
    exactly like success.
    """
    now = now or datetime.now(timezone.utc)
    url = _SCOREBOARD.format(league=league)
    cached = _CACHE / f"{league}_scoreboard.json"

    prior = _cached_copy(cached)
    if prior:
        raw, stamp = prior
        last = _iso(stamp)
        if not _playing(raw, now) and last and now - last < _PROBE:
            return raw, stamp             # between events, probed recently — no request
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.load(r)
        fetched_at = now.isoformat(timespec="minutes")
        _CACHE.mkdir(parents=True, exist_ok=True)
        # Stamped into our own copy so the age survives a file move, unlike an mtime.
        cached.write_text(json.dumps({**raw, _FETCHED_AT: fetched_at}))
        return raw, fetched_at
    except Exception as exc:
        if prior:
            # Graceful fallback to last-good — but say so on stderr and date it. Silently
            # serving a stale cache reads exactly like a working fetch, which is how a
            # days-old draw reaches the site looking live.
            print(f"warning: ESPN {league} fetch failed ({type(exc).__name__}: {exc}); "
                  f"using cache fetched {prior[1]}", file=sys.stderr)
            return prior
        raise


def _round_rank(label: str) -> "int | None":
    lab = (label or "").strip().lower()
    if "qualif" in lab or not lab:
        return None
    if lab in _ROUND_NAMED:
        return _ROUND_NAMED[lab]
    m = re.match(r"round (\d+)", lab)
    return int(m.group(1)) if m else 50


# Wikipedia's tier strings -> ours. The calendar feed is the first authority on level; the
# name heuristics below are the fallback for an event it doesn't cover (a brand-new stop, or
# a season page not yet refreshed).
_WIKI_TIERS = {"Grand Slam": GRAND_SLAM,
               "ATP 1000": MASTERS_1000, "WTA 1000": MASTERS_1000,
               "ATP 500": levels.TOUR_500, "WTA 500": levels.TOUR_500}


def _tier(event: dict, gender: str, cal: "dict | None" = None) -> str:
    if event.get("major"):
        return GRAND_SLAM
    name = event.get("name", "")
    city = levels.city((event.get("venue") or {}).get("displayName", ""))
    month = int((event.get("date") or "0000-00")[5:7] or 0) or None
    entry = feeds.lookup(city, name, gender, month, cal)
    if entry and entry.get("tier") in _WIKI_TIERS:
        return _WIKI_TIERS[entry["tier"]]
    if entry:
        return classify_tier(name, gender)  # covered, and below the levels we serve
    # Not in the calendar — a brand-new stop, or no calendar cached yet. Fall back to the
    # name heuristics, which read 1000s well but cannot see a 500 at all: without the
    # calendar feed the site serves slams and 1000s only, and says so rather than guessing.
    t = classify_tier(name, gender)
    if t == MASTERS_1000:
        return t
    # `classify_tier` matches a whole normalized name; an ESPN name is the sponsor's
    # ("Rolex Monte-Carlo Masters"), so the city has to be found inside it. Hyphens are
    # flattened for the same reason.
    low = name.lower().replace("-", " ")
    return MASTERS_1000 if any(c in low for c in CITIES_1000) else t


def _side(comp: dict) -> Side:
    ath = comp.get("athlete") or {}
    flag = comp.get("flag") or ath.get("flag") or {}
    lines = comp.get("linescores", [])
    return Side(name=ath.get("displayName") or "", country=flag.get("alt"),
                winner=bool(comp.get("winner")),
                sets=[ls.get("value") for ls in lines],
                set_wins=[ls.get("winner") for ls in lines])


def parse(raw: dict, cal: "dict | None" = None, fetched_at: str = "") -> "list[Tournament]":
    """Scoreboard JSON -> the singles draws we serve. ``cal`` is the calendar feed used to
    decide tour level; it's read from the cache when not supplied. ``fetched_at`` stamps each
    draw with the age of the scoreboard it came from."""
    out = []
    cal = feeds.load_calendar() if cal is None else cal
    for event in raw.get("events", []):
        for grouping in event.get("groupings", []):
            gender = _SINGLES.get((grouping.get("grouping") or {}).get("slug"))
            if not gender:
                continue
            tier = _tier(event, gender, cal)
            if tier not in _TARGET_TIERS:
                continue
            best_of = 5 if (gender == "M" and tier == GRAND_SLAM) else 3
            matches = []
            for c in grouping.get("competitions", []):
                rank = _round_rank((c.get("round") or {}).get("displayName", ""))
                cs = c.get("competitors", [])
                if rank is None or len(cs) != 2:
                    continue
                st = (c.get("status") or {}).get("type") or {}
                matches.append(Match(
                    id=str(c.get("id")), round_rank=rank,
                    round_label=(c.get("round") or {}).get("displayName", ""),
                    state=st.get("state", "pre"), detail=st.get("shortDetail", ""),
                    a=_side(cs[0]), b=_side(cs[1]), date=c.get("date") or ""))
            if matches:
                venue = (event.get("venue") or {}).get("displayName", "")
                out.append(Tournament(id=str(event.get("id")), name=event.get("name", ""),
                                      tier=tier, gender=gender, best_of=best_of,
                                      matches=matches, city=levels.city(venue),
                                      fetched_at=fetched_at))
    return out


def current_tournaments() -> "list[Tournament]":
    """Current Slam / 1000 / 500 singles draws from both tours (deduped by id+gender)."""
    seen, out = set(), []
    for league in ("atp", "wta"):
        raw, fetched_at = _fetch(league)
        for t in parse(raw, fetched_at=fetched_at):
            key = (t.id, t.gender)
            if key not in seen:
                seen.add(key)
                out.append(t)
    return out
