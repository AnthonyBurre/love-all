# Draw-slot fixtures

One small JSON file per tournament: the **round-1 slot order** (plus seeds/entry
tags) that turns the flat ESPN match list into a complete bracket tree. R1 order
determines everything — winners of slots 2k−1 and 2k meet at slot k of the next
round — so this is all the structure a draw ever needs. These files are
**committed**: they're static facts about an event, they change only when a new
draw is made (4 slams + 9 1000s a year), and no source that provides them is
fetchable from CI (ESPN/Sofascore/slam sites all bot-gate; verified 2026-07-04).

## Format

```json
{
  "source": "sofascore cuptrees (…ids…)",
  "fetched": "YYYY-MM-DD",
  "draws": [
    { "tournament": "Wimbledon", "gender": "M", "season": 2026,
      "r1": [ { "slot": 1, "a": "Jannik Sinner", "b": "Miomir Kecmanović",
                "seed_a": "1", "seed_b": null }, … ] }
  ]
}
```

`tournament` is matched against the ESPN feed's event name by substring (either
direction), so use the plain event name. Player names are matched fuzzily
(`live/players.normalize` + difflib), so accents/spacing differences vs ESPN are
fine. Seeds are strings: numbers, `Q`, `WC`, `LL`.

## Regenerating (once per event, needs a real browser)

Sofascore's cup-tree API has the cleanest structure and covers both tours and
the 1000s, but 403s non-browser clients — so harvest from a browser console:

1. Find the event ids: `https://www.sofascore.com/api/v1/search/all?q=<event>`
   → note the ATP and WTA `uniqueTournament` ids.
2. Seasons: `/api/v1/unique-tournament/<id>/seasons` → current season id.
3. Cup tree: `/api/v1/unique-tournament/<id>/season/<seasonId>/cuptrees` →
   `cupTrees[0].rounds`, take the `order: 1` round; each block gives
   `order` (= slot), `participants[].team.name`, `participants[].teamSeed`.
4. Write the file as above. `tests/test_draws.py` sanity-checks shape.

The consumer (`live/draws.py`) bails to name-inference linkage if a fixture
doesn't cleanly fit (wrong round count, byes, slot conflicts) — a bad fixture
degrades the bracket, it can't corrupt it.
