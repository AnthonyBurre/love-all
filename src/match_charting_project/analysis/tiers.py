"""Classify a free-text tournament name into a tour tier.

The Match Charting Project stores only the tournament *name* (637 distinct
values across 1960-2026, with naming drift). There is no tier field, so we
derive one heuristically.

Granularity note: even Jeff Sackmann's authoritative ATP data collapses 250- and
500-level events into a single code ("A"), because the distinction isn't cleanly
recoverable. We follow that honest granularity with a single "Tour (250/500)"
bucket rather than guessing. Splitting 250 vs 500 is a documented future upgrade
(cross-reference the tennis_atp / tennis_wta repos by name + date).
"""

import re

GRAND_SLAM = "Grand Slam"
MASTERS_1000 = "Masters / WTA 1000"
TOUR_FINALS = "Tour Finals"
TOUR_500_250 = "Tour (250/500)"
TEAM_EVENT = "Team / Other Event"
OTHER = "Other / Unknown"

# Display order from highest tier to lowest (used to order chart categories).
TIER_ORDER = [GRAND_SLAM, MASTERS_1000, TOUR_FINALS, TOUR_500_250, TEAM_EVENT, OTHER]

_GRAND_SLAMS = {
    "australian open", "roland garros", "french open", "wimbledon", "us open",
}

# WTA 1000 events appear WITHOUT a "Masters" suffix, so they need a name list.
# (ATP Masters 1000 events in this data reliably carry the "Masters" suffix.)
_WTA_1000 = {
    "indian wells", "miami", "madrid", "rome", "canada", "montreal", "toronto",
    "cincinnati", "beijing", "wuhan", "dubai", "doha", "guadalajara", "cancun",
    "tokyo", "charleston",
}
# A few ATP 1000s that may appear without the suffix in older naming.
_ATP_1000_EXTRA = {"monte carlo", "shanghai", "hamburg"}

_FINALS = {
    "tour finals", "atp finals", "wta finals", "masters cup",
    "wta championships", "year-end championships",
}
# Substrings that mark a team or non-tour event.
_TEAM_MARKERS = (
    "davis cup", "fed cup", "billie jean king cup", "united cup", "laver cup",
    "hopman cup", "atp cup", "olympic",
)


def _normalize(name: str) -> str:
    """Lowercase, drop the 'Masters' suffix, collapse whitespace."""
    s = (name if isinstance(name, str) else "").strip().lower().replace("&", "and")
    s = re.sub(r"\bmasters\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def classify_tier(tournament: str, gender: str = "") -> str:
    raw = (tournament if isinstance(tournament, str) else "").strip().lower()
    base = _normalize(tournament)
    if not base:
        return OTHER
    if base in _GRAND_SLAMS:
        return GRAND_SLAM
    if raw in _FINALS or base in _FINALS:
        return TOUR_FINALS
    if any(marker in raw for marker in _TEAM_MARKERS):
        return TEAM_EVENT
    if "masters" in raw or base in _ATP_1000_EXTRA:
        return MASTERS_1000
    if str(gender).upper() == "W" and base in _WTA_1000:
        return MASTERS_1000
    # Remaining alphabetic names are treated as main-tour stops; the MCP charts
    # very few sub-tour events, so this is a reasonable floor.
    if re.search(r"[a-z]", base):
        return TOUR_500_250
    return OTHER
