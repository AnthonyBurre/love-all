"""Overlay the live feed onto a draw's slot scaffold.

ESPN's feed has no draw positions (see brackets.py). A draw's structure is *static once
made*, though: the round-1 slot order determines every future pairing (winners of slots
2k-1 and 2k meet at slot k of the next round), so one ordered list of round-1 slots is all
the structure a bracket ever needs. ``live.feeds`` sources that list from Wikipedia and
caches it; this module overlays the live matches onto it by player name.

Output mirrors ``brackets.rounds()``: every slot of every round is present — live
matches where they're known, synthetic placeholders (id ``slot-<round>-<k>``)
where they're not — with ``feeds``/``slot``/``seed`` filled in structurally, so
the site can draw the complete path to the final from day one.
"""

from dataclasses import dataclass, field
from difflib import get_close_matches

from match_charting_project.live.espn import Side
from match_charting_project.live.players import normalize

BYE = "Bye"


@dataclass
class Placeholder:
    """A structural bracket slot with no live match mapped to it (yet)."""

    id: str
    round_rank: int
    round_label: str
    a: Side
    b: Side
    state: str = "pre"
    detail: str = ""
    feeds: "str | None" = None
    slot: int = 0
    placeholder: bool = field(default=True)
    bye: bool = field(default=False)


def _name_tables(fixture) -> "tuple[dict, dict]":
    """normalized player name -> R1 slot, and -> seed/entry tag ('1', 'Q', 'WC', …)."""
    slots, seeds = {}, {}
    for entry in fixture["r1"]:
        for side, seed in (("a", "seed_a"), ("b", "seed_b")):
            if entry.get(side):
                n = normalize(entry[side])
                slots[n] = entry["slot"]
                if entry.get(seed):
                    seeds[n] = entry[seed]
    return slots, seeds


def _bye_slots(fixture) -> dict:
    """R1 slot -> the entrant who sits the round out, for a field short of a power of two.

    A 28- or 48-player draw gives its top seeds a bye, which the fixture records as a slot
    with one named side. No match is ever played in those slots, so the feed has nothing to
    map there — without this they'd read as an undecided TBD rather than a seed already
    through to the next round.
    """
    out = {}
    for entry in fixture["r1"]:
        named = [entry[k] for k in ("a", "b") if entry.get(k)]
        if len(named) == 1:
            out[entry["slot"]] = named[0]
    return out


def _lookup(norm: str, table: dict, cutoff: float = 0.85):
    if norm in table:
        return table[norm]
    close = get_close_matches(norm, list(table), n=1, cutoff=cutoff)
    return table[close[0]] if close else None


def _slot_at(r1_slot: int, round_no: int) -> int:
    return (r1_slot - 1) // (2 ** (round_no - 1)) + 1


def slot_rounds(tournament, fixture) -> "list | None":
    """``brackets.rounds()``-shaped list with every slot filled, or None if the
    fixture doesn't cleanly describe this tournament (caller then falls back)."""
    n = len(fixture["r1"])
    if n < 2 or n & (n - 1):                    # must be a power of two
        return None
    n_rounds = n.bit_length()                   # 64 -> 7 rounds

    by_rank: dict = {}
    for m in tournament.matches:
        by_rank.setdefault(m.round_rank, []).append(m)
    ranks = sorted(by_rank)
    if len(ranks) != n_rounds:                  # byes / partial feed: not slot-safe
        return None

    slots_tbl, seeds_tbl = _name_tables(fixture)
    label = {r: by_rank[r][0].round_label for r in ranks}

    # Place each live match whose named players trace back to an R1 slot.
    placed: dict = {}                           # (round_no, slot) -> match
    for round_no, rank in enumerate(ranks, start=1):
        for m in by_rank[rank]:
            votes = set()
            for s in (m.a, m.b):
                if s.name and s.name != "TBD":
                    r1_slot = _lookup(normalize(s.name), slots_tbl)
                    if r1_slot:
                        votes.add(_slot_at(r1_slot, round_no))
            if len(votes) != 1:                 # unknown or conflicting: leave unplaced
                continue
            slot = votes.pop()
            if placed.setdefault((round_no, slot), m) is not m:
                return None                     # two matches claim one slot: distrust all

    # A round's leftover TBD-vs-TBD matches are interchangeable, so adopting one is
    # only safe when there's exactly one of them and one empty slot (e.g. the final —
    # keeps its ESPN id and schedule detail clickable instead of a bare placeholder).
    for round_no, rank in enumerate(ranks, start=1):
        taken = {m.id for (r, _), m in placed.items() if r == round_no}
        leftover = [m for m in by_rank[rank] if m.id not in taken]
        empty = [s for s in range(1, n // (2 ** (round_no - 1)) + 1)
                 if (round_no, s) not in placed]
        if len(leftover) == 1 and len(empty) == 1:
            placed[(round_no, empty[0])] = leftover[0]

    # Assemble the full scaffold: live match, bye, or placeholder at every slot.
    byes = _bye_slots(fixture)
    out = []
    for round_no, rank in enumerate(ranks, start=1):
        matches = []
        for slot in range(1, n // (2 ** (round_no - 1)) + 1):
            m = placed.get((round_no, slot))
            if m is None:
                through = byes.get(slot) if round_no == 1 else None
                m = Placeholder(id=f"slot-{round_no}-{slot}", round_rank=rank,
                                round_label=label[rank],
                                a=Side(through or "TBD", None, False, []),
                                b=Side(BYE if through else "TBD", None, False, []),
                                bye=bool(through))
            m.slot = slot
            m.feeds = f"slot-{round_no + 1}-{(slot - 1) // 2 + 1}" if round_no < n_rounds else None
            for s in (m.a, m.b):
                anonymous = not s.name or s.name in ("TBD", BYE)
                s.seed = None if anonymous else _lookup(normalize(s.name), seeds_tbl)
            matches.append(m)
        out.append({"rank": rank, "label": label[rank], "matches": matches})

    # feeds must point at real ids where the target slot holds a live match.
    id_at = {(r, m.slot): m.id for r, rd in enumerate(out, start=1) for m in rd["matches"]}
    for round_no, rd in enumerate(out, start=1):
        for m in rd["matches"]:
            if m.feeds:
                m.feeds = id_at[(round_no + 1, (m.slot - 1) // 2 + 1)]
    return out
