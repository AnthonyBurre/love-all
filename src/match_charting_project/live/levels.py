"""The 500-level tier label, and the venue-city helper the feeds agree on.

Levels come from ``live.feeds``, which re-reads the Wikipedia season pages and updates
itself. ESPN's feed states no tour level and ``analysis.tiers`` deliberately collapses 250
and 500 (Jeff Sackmann's ATP data does the same — "A" for both — and the split isn't
recoverable from a tournament name), so a hand-written roster of 500s is the alternative.
It is not a viable one: a list days old already had Eastbourne, Hong Kong and Seoul at 500
when all three are 250s, and was missing Dallas, Queen's WTA and Singapore.

What lives here: the tier label, and ``city()`` — the venue city is how the live feed, the
charted database and the calendar all agree on which event they mean, since the feed names
events after sponsors ("Mubadala DC Open"), the database after cities ("Washington"), and
the calendar after common names ("Washington Open").
"""

TOUR_500 = "ATP / WTA 500"


def tournament_id(event_id: str) -> str:
    """ESPN's stable per-tournament id, with the season stripped: '888-2026' -> '888'."""
    return str(event_id or "").split("-")[0]


def city(venue_display: str) -> str:
    """The city out of ESPN's venue string: 'Washington, USA' -> 'Washington'."""
    return (venue_display or "").split(",")[0].strip()
