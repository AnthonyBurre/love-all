"""Turn a flat list of a tournament's matches into ordered bracket rounds.

ESPN gives round-tagged matches but no bracket object; grouping by round rank is enough
to render the standard column-per-round view. (Forward linkage — wiring each winner to
their next-round match to draw connectors — is a documented stretch; the round columns
stand on their own.)
"""


def rounds(tournament) -> list:
    """``[{'rank', 'label', 'matches':[...]}, ...]`` ordered first round → final."""
    by_rank: dict = {}
    for m in tournament.matches:
        r = by_rank.setdefault(m.round_rank, {"rank": m.round_rank, "label": m.round_label,
                                              "matches": []})
        r["matches"].append(m)
    return [by_rank[r] for r in sorted(by_rank)]
