# Shot-making triggers: when a player pulls the trigger, and whether they should

`shot_patterns` keeps two separate books on every player: the lead-ups that
precede their **winners** and the lead-ups that precede their **unforced
errors**. This experiment asks whether those are really two books at all. A
winner and an unforced error share a decision — the player *went for a
finishing shot* — and differ only in execution. If the same contexts sit high
in both lists, the behavioral unit is the **attempt**, and outcome is
conversion.

Recasting in those terms gives three things the separate lists can't:

1. **Trigger patterns** — per context, the player's *attempt rate*
   (winner + unforced error, per stroke) vs their own baseline: which
   sequences make them pull the trigger.
2. **Traps vs green lights** — among their trigger contexts, split by
   *conversion* (winners / attempts) against their own conversion baseline. A
   high-attempt, low-conversion context is exactly "a sequence that makes them
   go for a difficult finishing shot": they take the bait and don't cash it.
   A player with **no trap contexts** is immune in the sense that matters —
   their extra aggression shows up only where it pays.
3. **Pattern-immunity** — σ, the true between-context spread of a player's
   attempt rate (beta-binomial method of moments, so the binomial noise floor
   is subtracted and charting volume doesn't distort the comparison). σ ≈ 0
   means their go-for-it decisions look context-independent (nothing baits
   them *or* greenlights them); large σ means strongly cue-driven.

## Method

Same counting machinery as `shot_patterns` (two-shot lead-up context from the
`shot_language` tokens; the player's stroke marked winner `*` / unforced `@` /
forced `#`; forced errors excluded from attempts as opponent-caused). Per
qualifying player: context attempt/conversion tables, the winner-rate ×
error-rate correlation across contexts (the "are these the same book?" test),
the σ dispersion score, and the trap/green-light split. Pure counting — no
model.

## Honest limitations

- **"Attempt" is a proxy.** Not every unforced error is a failed finishing
  shot (some are routine misses), and some winners are gifts. At our token
  resolution winner+unforced is the honest available proxy for shot-making
  risk; the README of `shot_patterns` carries the same coarseness caveats.
- **Conversion is context-selected.** Comparing conversion across contexts
  within one player is fair; comparing conversion across players also reflects
  shot selection, opposition, and charting coverage.
- σ needs many well-populated contexts, so the immunity leaderboard is
  restricted to heavily-charted players.

Run: `python experiments/shot_triggers/run.py` → `reports/shot_triggers.md`,
`reports/shot_triggers.csv`, `reports/figures/shot_triggers.png`.
