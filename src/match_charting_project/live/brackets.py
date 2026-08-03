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


def rounds(tournament, use_fixture: bool = True) -> list:
    """``[{'rank', 'label', 'matches':[...]}, ...]`` ordered first round → final.

    Each match gains a ``feeds`` attribute: the id of the next-round match its winner
    advances to, or ``None`` while unresolved (or on the final).

    When a draw sheet is cached for this tournament (``live.feeds``, sourced from Wikipedia
    and only adopted once it agrees with the feed about first-round pairings), the bracket is
    instead assembled on its slot scaffold — every slot of every round present (placeholders
    where undecided, byes where the field is short of a power of two), the full path to the
    final known from day one. Name inference below is the fallback for a tournament whose
    draw isn't published or didn't validate, and the only path for ``use_fixture=False``
    (harvested past draws, whose slot order the current-season sheet would misrepresent — a
    fully resolved draw links cleanly by name anyway).
    """
    if use_fixture:
        from match_charting_project.live import draws, feeds

        fx = feeds.fixture_for(tournament)
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


def _side_dict(s) -> dict:
    """ESPN-native side fields only — no ``matched``/``charted`` (those are DB-derived and
    applied fresh at emit time, so an archived snapshot never carries stale annotation)."""
    return {"name": s.name, "country": s.country, "winner": s.winner,
            "sets": s.sets, "seed": getattr(s, "seed", None)}


def serialize(tournament, use_fixture: bool = True) -> dict:
    """A tournament as a JSON-ready payload dict (the ``brackets.json`` tournament shape).

    Structure, plus the ``event`` block of reader-facing labels (common name, tour level,
    surface — see ``feeds.event_meta``). Used for both live draws and the accumulating
    history archive, so an event's labels freeze into the archive with its draw rather than
    being re-derived later from a calendar that has moved on to the next season.
    """
    from match_charting_project.live import feeds

    rds = rounds(tournament, use_fixture=use_fixture)
    slotted = all(getattr(m, "slot", 0) for r in rds for m in r["matches"])
    try:
        meta = feeds.event_meta(tournament)
    except Exception:
        meta = {}                         # no calendar cached: the feed name stands alone
    return {
        "id": tournament.id, "name": tournament.name, "tier": tournament.tier,
        "city": getattr(tournament, "city", ""), "event": meta,
        "gender": tournament.gender, "best_of": tournament.best_of, "slotted": slotted,
        "rounds": [
            {"rank": r["rank"], "label": r["label"], "matches": [
                {"id": m.id, "state": m.state, "detail": m.detail, "feeds": m.feeds,
                 "placeholder": getattr(m, "placeholder", False),
                 "bye": getattr(m, "bye", False),
                 "date": getattr(m, "date", None),
                 "a": _side_dict(m.a), "b": _side_dict(m.b)}
                for m in r["matches"]]}
            for r in rds],
    }
