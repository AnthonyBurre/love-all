# Player finishing & breakdown patterns

Per-player: **which rally lead-ups make them go for a winner, and which make them err
and lose the point.** It uses the two things the data supports at this resolution, the
**shot-type/zone tokens** (`shot_language`) and the **charted outcome** (winner `*` /
unforced `@` / forced `#`), not precise placement. Shot kind and zone 1/2/3 are enough
to see a player's tactical fingerprint.

## How it works

For every stroke a player hits, take the **two shots before it** as the context and record
whether that stroke is a winner, an unforced error, or neither. A pattern reads:

> `[your setup shot] · [opponent's reply] → your stroke`

(shots alternate, so the shot two back is the player's own, the one just before is the
opponent's). Per context, the player's winner rate and error rate against their own
baseline (lift). Counting only, no model.

```bash
uv run python experiments/shot_patterns/run.py
```

Writes `reports/shot_patterns.md` (marquee players) and `reports/shot_patterns.csv` (every
qualifying player × context, to slice yourself).

## What it finds

- **Pete Sampras** — the green light is **net play** (`FH net→3 · BH … → 71% winner`);
  the serve-volleyer finishes at the net. Highest winner baseline of the group
  (13.8%/stroke).
- **Roger Federer** — finishes off **forehand corner → weak backhand reply → put-away**
  (≈69% winner, ~6.8×); his *trouble* is **backhand-to-backhand exchanges** (~1.7× his
  error rate), his well-known pressure point.
- **Novak Djokovic** — far fewer winners per stroke (6.4% against Federer's 10.2%);
  trouble shows up in **slice exchanges**.
- **Martina Navratilova** — the green light is **serve-wide + slice → winner** (serve+1),
  her serve-volley/slice game.

The green-light patterns share an obvious core (a weak reply is easy to put away), but how
each player creates the weak ball differs (forehand to the corner, a wide serve, a net
approach), and the trouble patterns are individual (Federer's backhand
wing, Sampras's slice exchanges).

## Where it sits

This is the third view of a player: `player_styles` says **what** shots a player hits
(static mix), `shot_language` says **in what order** (sequence/predictability), and this
says **which orders pay off** (winner) or **cost** (error).

`../shot_triggers` treats these two books as one: winner and error contexts overlap
because both mark the same *aggressive shot*. See it for frequency and conversion, traps,
and pattern immunity.

## Limitations

- **Coarse tokens.** Zones are thirds and shot kind is drive/slice/net/drop/lob/other:
  enough for tactics, not for spin, pace or exact placement.
- **Reactive & opponent-dependent.** A pattern is "style in context"; a weak reply that
  precedes a winner is partly the opponent's doing.
- **Sample sizes vary** (a marquee modern baseliner has ~160k strokes; Navratilova ~7k),
  so small-n contexts are only indicative; the CSV carries `n` for every row.
- Same charting-coverage caveat as the rest of the repo.
