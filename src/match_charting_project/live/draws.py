"""Draw-slot fixtures: the committed bracket structure no live feed will hand us.

ESPN's feed has no draw positions (see brackets.py), and every source that does —
ESPN's bracket pages, Sofascore's cup trees, even the slams' own per-draw feeds —
sits behind bot protection that CI can't pass. But a draw's structure is *static
once made*: the round-1 slot order determines every future pairing (winners of
slots 2k-1 and 2k meet at slot k of the next round). So the structure is committed
as a tiny fixture file per tournament in ``data/draws/`` (~64 ordered R1 pairs +
seeds, harvested once per event from a browser), and this module overlays the live
ESPN matches onto that scaffold by player name.

Output mirrors ``brackets.rounds()``: every slot of every round is present — live
matches where they're known, synthetic placeholders (id ``slot-<round>-<k>``)
where they're not — with ``feeds``/``slot``/``seed`` filled in structurally, so
the site can draw the complete path to the final from day one.
"""

import json
from dataclasses import dataclass, field
from difflib import get_close_matches

from match_charting_project.live.espn import Side
from match_charting_project.live.players import normalize
from match_charting_project.paths import PROJECT_ROOT

DRAWS_DIR = PROJECT_ROOT / "data" / "draws"


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


def load_fixtures() -> list:
    """All committed draw fixtures, flattened to one entry per (tournament, gender)."""
    out = []
    if not DRAWS_DIR.is_dir():
        return out
    for path in sorted(DRAWS_DIR.glob("*.json")):
        doc = json.loads(path.read_text())
        out.extend(doc.get("draws", []))
    return out


def find_fixture(name: str, gender: str, fixtures: "list | None" = None) -> "dict | None":
    """The fixture whose tournament name appears in (or contains) the feed's name."""
    for fx in load_fixtures() if fixtures is None else fixtures:
        if fx.get("gender") != gender:
            continue
        a, b = fx.get("tournament", "").lower(), (name or "").lower()
        if a and (a in b or b in a):
            return fx
    return None


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

    # Assemble the full scaffold: live match or placeholder at every slot.
    out = []
    for round_no, rank in enumerate(ranks, start=1):
        matches = []
        for slot in range(1, n // (2 ** (round_no - 1)) + 1):
            m = placed.get((round_no, slot))
            if m is None:
                m = Placeholder(id=f"slot-{round_no}-{slot}", round_rank=rank,
                                round_label=label[rank],
                                a=Side("TBD", None, False, []), b=Side("TBD", None, False, []))
            m.slot = slot
            m.feeds = f"slot-{round_no + 1}-{(slot - 1) // 2 + 1}" if round_no < n_rounds else None
            for s in (m.a, m.b):
                s.seed = _lookup(normalize(s.name), seeds_tbl) if s.name and s.name != "TBD" else None
            matches.append(m)
        out.append({"rank": rank, "label": label[rank], "matches": matches})

    # feeds must point at real ids where the target slot holds a live match.
    id_at = {(r, m.slot): m.id for r, rd in enumerate(out, start=1) for m in rd["matches"]}
    for round_no, rd in enumerate(out, start=1):
        for m in rd["matches"]:
            if m.feeds:
                m.feeds = id_at[(round_no + 1, (m.slot - 1) // 2 + 1)]
    return out
