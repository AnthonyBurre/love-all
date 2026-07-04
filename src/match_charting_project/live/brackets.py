"""Turn a flat list of a tournament's matches into ordered bracket rounds with linkage.

ESPN gives round-tagged matches but no bracket object — no draw slots, no seeds, and
neither feed order nor match ids encode position. What *is* recoverable is progression:
a player in round N+1 must have won a round-N match, so matching names across adjacent
rounds yields each match's ``feeds`` link (the next-round match its winner advances to).
Links resolve as the draw resolves — a fresh, unplayed draw has none, mid-tournament
most — and the site draws connectors only for known links.

Within each round, matches are ordered by the mean position of their known feeders so
linked matches sit near each other; unlinked matches keep feed order after them.
"""


def _names(m) -> "list[str]":
    return [s.name for s in (m.a, m.b) if s.name and s.name != "TBD"]


def _link(rounds: list) -> None:
    """Set ``feeds`` (next-round match id) on each match dict, by name progression."""
    for earlier, later in zip(rounds, rounds[1:]):
        entrant, dupes = {}, set()        # player name -> next-round match id
        for m in later["matches"]:
            for n in _names(m):
                dupes.add(n) if n in entrant else entrant.setdefault(n, m.id)
        for n in dupes:
            del entrant[n]
        for m in earlier["matches"]:
            hits = {entrant[n] for n in _names(m) if n in entrant}
            # A name can only advance to one match; a duplicated or conflicting name
            # upsets the mapping — safer to claim nothing than to wire it wrong.
            m.feeds = hits.pop() if len(hits) == 1 else None


def _order(rounds: list) -> None:
    """Reorder each round so matches sit near the match they feed (stable for ties)."""
    for earlier, later in zip(rounds[::-1][1:], rounds[::-1]):
        pos = {m.id: i for i, m in enumerate(later["matches"])}
        linked = len(later["matches"])    # unlinked matches sort after all linked ones
        earlier["matches"].sort(key=lambda m, p=pos, u=linked: p.get(m.feeds, u))


def rounds(tournament) -> list:
    """``[{'rank', 'label', 'matches':[...]}, ...]`` ordered first round → final.

    Each match gains a ``feeds`` attribute: the id of the next-round match its winner
    advances to, or ``None`` while unresolved (or on the final).

    When a committed draw fixture exists for this tournament (``data/draws/``), the
    bracket is instead assembled on the fixture's slot scaffold — every slot of every
    round present (placeholders where undecided), the full path to the final known
    from day one. Name inference below is the fallback for uncovered tournaments.
    """
    from match_charting_project.live import draws

    fx = draws.find_fixture(tournament.name, tournament.gender)
    if fx:
        out = draws.slot_rounds(tournament, fx)
        if out:
            return out

    by_rank: dict = {}
    for m in tournament.matches:
        m.feeds = None
        r = by_rank.setdefault(m.round_rank, {"rank": m.round_rank, "label": m.round_label,
                                              "matches": []})
        r["matches"].append(m)
    out = [by_rank[r] for r in sorted(by_rank)]
    _link(out)
    _order(out)
    return out
