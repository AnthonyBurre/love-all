"""The 500-level tier label, and the venue-city helper the feeds agree on.

This module used to carry a hand-written roster of ATP/WTA 500s keyed by ESPN tournament
id, because ESPN's feed states no tour level and ``analysis.tiers`` deliberately collapses
250 and 500 (Jeff Sackmann's ATP data does the same — "A" for both — and the split isn't
recoverable from a tournament name).

That roster is gone. Checked against the Wikipedia calendar feed it had Eastbourne, Hong
Kong and Seoul at 500 when all three are 250s, and was missing Dallas, Queen's WTA and
Singapore — six errors in a list days old, which is what hand-kept tour metadata does.
Levels now come from ``live.feeds``, which re-reads the season pages and updates itself.

What stays here: the tier label, and ``city()`` — the venue city is how the live feed, the
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
