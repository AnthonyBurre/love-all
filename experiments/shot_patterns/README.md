# Player finishing & breakdown patterns

Per-player: **which rally lead-ups make them go for a winner, and which make them err and
lose the point.** Built deliberately on the two things the data supports at our resolution
— the **shot-type/zone tokens** (`shot_language`) and the **charted outcome** (winner `*` /
unforced `@` / forced `#`) — *not* precise placement. So it sidesteps the resolution problem
that would sink a placement "tablebase": net-vs-slice-vs-drive and zone 1/2/3 are enough to
see a player's tactical fingerprint.

## How it works

For every stroke a player hits, take the **two shots before it** as the context and record
whether that stroke is a winner, an unforced error, or neither. A pattern reads:

> `[your setup shot] · [opponent's reply] → your stroke`

(shots alternate, so the shot two back is the player's own, the one just before is the
opponent's). Per context we get the player's winner-rate and error-rate, compared to their
own baseline (lift). Pure counting — no model.

```bash
uv run python experiments/shot_patterns/run.py
```

Writes `reports/shot_patterns.md` (marquee players) and `reports/shot_patterns.csv` (every
qualifying player × context, to slice yourself).

## What it finds (face-valid, and player-distinctive)

- **Pete Sampras** — green light is **net play** (`FH net→3 · BH … → 71% winner`); the
  serve-volleyer finishes at the net. Highest winner baseline of the group (13.8%/stroke).
- **Roger Federer** — finishes off the **forehand-corner → weak backhand reply → put-away**
  (≈69% winner, ~6.8×); his *trouble* is **backhand-to-backhand exchanges** (~1.7× his error
  rate), the textbook Federer pressure point.
- **Novak Djokovic** — far fewer winners per stroke (6.4% vs Federer's 10.2% — the wall vs
  the finisher); trouble shows up in **slice exchanges**.
- **Martina Navratilova** — green light is **serve-wide + slice → winner** (serve+1), her
  serve-volley/slice game.

The *green-light* patterns share a tautological core (a weak reply is easy to put away), but
*how* each player manufactures the weak ball differs — forehand to the corner, a wide serve,
a net approach — and the *trouble* patterns are genuinely individual (Federer's backhand
wing, Sampras's slice exchanges).

## Where it sits

This is the third lens on a player, and they compose: `player_styles` says **what** shots a
player hits (static mix), `shot_language` says **in what order** (sequence/predictability),
and this says **which orders pay off** (winner) or **cost** (error).

## Honest limitations

- **Coarse tokens.** Zones are the codebook's 1/2/3, shot "kind" is drive/slice/net/other —
  enough for tactics, not for spin/pace/exact placement.
- **Reactive & opponent-dependent.** A pattern is "style in context"; a weak reply that
  precedes a winner is partly the opponent's doing.
- **Sample sizes vary** (a marquee modern baseliner has ~160k strokes; Navratilova ~7k), so
  the small-n contexts are indicative — the CSV carries `n` for every row.
- Same charting-coverage caveat as the rest of the repo.
