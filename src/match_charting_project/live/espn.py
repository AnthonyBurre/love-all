"""ESPN's unofficial tennis JSON API — the swappable live source adapter.

All ESPN-specific JSON shapes are confined to this module; everything downstream
consumes the neutral ``Tournament`` / ``Match`` / ``Side`` dataclasses, so a paid feed
could replace it without touching the site. Free, no key, near-real-time — but
unofficial, so we cache the last successful raw JSON and fall back to it on failure.

Shape (verified against the live endpoint):
  events[]            → a tournament (``major`` flags a Grand Slam)
    groupings[]       → a draw; ``grouping.slug`` = mens-singles / womens-singles / …
      competitions[]  → a match: ``round.displayName``, ``status.type.state``, competitors[]
        competitors[] → ``athlete.displayName`` / ``flag.alt`` / ``winner`` / ``linescores[]``
"""

import json
import re
import urllib.request
from dataclasses import dataclass

from match_charting_project.analysis.tiers import GRAND_SLAM, MASTERS_1000, classify_tier
from match_charting_project.paths import PROJECT_ROOT

_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/tennis/{league}/scoreboard"
_CACHE = PROJECT_ROOT / "data" / "live"
_SINGLES = {"mens-singles": "M", "womens-singles": "W"}
_TARGET_TIERS = (GRAND_SLAM, MASTERS_1000)
# Round display-name -> sortable rank (main draw only; qualifying excluded).
_ROUND_NAMED = {"final": 100, "semifinal": 99, "semifinals": 99,
                "quarterfinal": 98, "quarterfinals": 98,
                "round of 16": 4, "round of 32": 3, "round of 64": 2, "round of 128": 1}
# Combined 1000-level cities (ESPN doesn't flag 1000s; `major` only marks slams).
_M1000_CITIES = {"indian wells", "miami", "madrid", "rome", "monte", "cincinnati",
                 "shanghai", "canada", "montreal", "toronto", "paris masters", "dubai",
                 "doha", "beijing", "wuhan", "guadalajara", "cancun", "tokyo",
                 "charleston", "hamburg"}


@dataclass
class Side:
    name: str
    country: "str | None"
    winner: bool
    sets: list          # per-set games won (linescores)


@dataclass
class Match:
    id: str
    round_rank: int     # sortable (1 = first main-draw round … 100 = final)
    round_label: str    # "Round 1", "Quarterfinal", …
    state: str          # pre | in | post
    detail: str         # ESPN shortDetail (time, live score, or "Final")
    a: Side
    b: Side


@dataclass
class Tournament:
    id: str
    name: str
    tier: str
    gender: str         # M | W
    best_of: int
    matches: list


def _fetch(league: str) -> dict:
    url = _SCOREBOARD.format(league=league)
    cached = _CACHE / f"{league}_scoreboard.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "match-charting-project"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.load(r)
        _CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(raw))
        return raw
    except Exception:
        if cached.exists():
            return json.loads(cached.read_text())   # graceful fallback to last-good
        raise


def _round_rank(label: str) -> "int | None":
    lab = (label or "").strip().lower()
    if "qualif" in lab or not lab:
        return None
    if lab in _ROUND_NAMED:
        return _ROUND_NAMED[lab]
    m = re.match(r"round (\d+)", lab)
    return int(m.group(1)) if m else 50


def _tier(event: dict, gender: str) -> str:
    if event.get("major"):
        return GRAND_SLAM
    name = event.get("name", "")
    t = classify_tier(name, gender)
    if t == MASTERS_1000:
        return t
    low = name.lower()
    return MASTERS_1000 if any(c in low for c in _M1000_CITIES) else t


def _side(comp: dict) -> Side:
    ath = comp.get("athlete") or {}
    flag = comp.get("flag") or ath.get("flag") or {}
    return Side(name=ath.get("displayName") or "", country=flag.get("alt"),
                winner=bool(comp.get("winner")),
                sets=[ls.get("value") for ls in comp.get("linescores", [])])


def parse(raw: dict) -> "list[Tournament]":
    out = []
    for event in raw.get("events", []):
        for grouping in event.get("groupings", []):
            gender = _SINGLES.get((grouping.get("grouping") or {}).get("slug"))
            if not gender:
                continue
            tier = _tier(event, gender)
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
                    a=_side(cs[0]), b=_side(cs[1])))
            if matches:
                out.append(Tournament(id=str(event.get("id")), name=event.get("name", ""),
                                      tier=tier, gender=gender, best_of=best_of,
                                      matches=matches))
    return out


def current_tournaments() -> "list[Tournament]":
    """Current Slam / 1000 singles draws from both tours (deduped by id+gender)."""
    seen, out = set(), []
    for league in ("atp", "wta"):
        for t in parse(_fetch(league)):
            key = (t.id, t.gender)
            if key not in seen:
                seen.add(key)
                out.append(t)
    return out
