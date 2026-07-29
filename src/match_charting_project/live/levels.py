"""Which 500-level events the live site serves, as a curated roster.

ESPN's feed carries no tour level. ``major`` flags the four slams and nothing else, so
a 500 and a 125 arrive looking identical — the week this was written, Washington (500),
Los Cabos (250) and three WTA 125s were all live and indistinguishable in the JSON. The
historical classifier (``analysis.tiers``) is no help either: it collapses 250 and 500
into one bucket on purpose, because Jeff Sackmann's ATP data does the same ("A" for
both) and the split isn't recoverable from a tournament name.

So the 500s are listed by hand, keyed by **ESPN's tournament id** — the digits before
the year in an event id (``"888-2026"`` -> ``"888"``). That id is the only stable handle
the feed gives:

* Sponsor names churn. Washington is "Mubadala DC Open" now and was "Citi Open"; Queen's
  arrives as "HSBC Championships", with no city in it at all.
* Venue cities collide. A WTA 125 plays Rome and Hamburg too, so matching on city would
  promote it to a tier it isn't.

Ids are keyed **per gender**, because a combined id can straddle levels: Dubai and
Beijing are ATP 500 but WTA 1000 under one shared event id.

Keeping this current is a one-line edit when an event changes level (Munich moved up to
500 in 2025, Doha in 2024) or a new one appears. Anything unlisted falls back to
``tiers.classify_tier``, which for a 250 or a 125 means it never reaches the site.
"""

TOUR_500 = "ATP / WTA 500"

# ESPN tournament id -> city, for readability. Cities are comments, not lookup keys.
ATP_500 = {
    "4": "Rotterdam",
    "119": "Doha",
    "25": "Dubai",
    "375": "Rio de Janeiro",
    "711": "Acapulco",
    "338": "Barcelona",
    "12": "Munich",
    "942": "Hamburg",
    "27": "Halle",
    "129": "London (Queen's Club)",
    "888": "Washington",
    "959": "Beijing",
    "5": "Tokyo",
    "10": "Vienna",
    "23": "Basel",
}

WTA_500 = {
    "970": "Brisbane",
    "611": "Adelaide",
    "930": "Abu Dhabi",
    "199": "Linz",
    "911": "Mérida",
    "228": "Charleston",
    "254": "Stuttgart",
    "237": "Strasbourg",
    "635": "Berlin",
    "636": "Bad Homburg",
    "444": "Eastbourne",
    "888": "Washington",
    "341": "Monterrey",
    "887": "Guadalajara",
    "811": "Seoul",
    "264": "Tokyo",
    "963": "Ningbo",
    "380": "Hong Kong",
}

_ROSTER = {"M": ATP_500, "W": WTA_500}


def tournament_id(event_id: str) -> str:
    """ESPN's stable per-tournament id, with the season stripped: '888-2026' -> '888'."""
    return str(event_id or "").split("-")[0]


def level(event_id: str, gender: str) -> "str | None":
    """``TOUR_500`` if this event is a rostered 500 for this tour, else None."""
    if tournament_id(event_id) in _ROSTER.get(gender, {}):
        return TOUR_500
    return None


def city(venue_display: str) -> str:
    """The city out of ESPN's venue string: 'Washington, USA' -> 'Washington'.

    The charted database names tournaments by city ('Washington', 'Cincinnati') while the
    feed names them by sponsor, so this is what the two sides agree on.
    """
    return (venue_display or "").split(",")[0].strip()
