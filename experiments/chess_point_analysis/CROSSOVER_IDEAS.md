# Chess → tennis crossover ideas

Ways chess-analysis techniques map onto individual tennis points, beyond the
win-probability eval and shot-quality work this spike started. Each builds on the same
foundation: a point string is a tokenized, alternating-turn move list (decoder:
`match_charting_project.shots.notation`).

## Built

All of these graduated into `match_charting_project.shots`:

- **Engine eval** → empirical `P(server wins | rally state)` (`shots.winprob`).
- **Opening explorer** → `explore_state()`, next-stroke distribution and win% from a state.
- **Centipawn loss / blunder / accuracy** → per-stroke WPA and decision quality
  (`shots.quality`).
- **Annotated game** → `render_point()`.

Built as sibling experiments:

- **Shot-sequence language model** *(chess: n-gram models on PGN)* → `../shot_language`:
  order-2 Markov book, per-player predictability and perplexity, surprise mining, rally
  generation.
- **Player style fingerprint** *(chess: opening repertoire classification)* →
  `../player_styles`, which `../class_relative_wpa` then tried to rate decision quality
  against.
- **Tactical motif mining** *(chess: forks, pins, recurring motifs)* → `../shot_patterns`
  mines per-player finishing and breakdown contexts; `../shot_triggers` unifies the two
  books into aggressive shot frequency and conversion. Named-motif detection
  (serve-and-volley, wrong-foot) is still open.
- **Score-aware eval** *(tennis-specific extension)* → `../score_aware_eval`, settled
  negative: folding the score into the eval does not improve it (Klaassen–Magnus point
  independence). That negative is what justified the analytic score tree in
  `../match_winprob` for leverage instead.

## Open

### Finishing "tablebase" *(chess: endgame tablebases)*

For terminal 1–2 stroke situations there is enough data for near-exact empirical win
probabilities — "at net, opponent passing from the deuce corner" → put-away rate.
`../shot_patterns` sidestepped it: the notation's placement resolution (zones 1–3, no
court position) is too coarse, so this needs a resolution-honest reformulation first.

### Point phases *(chess: opening / middlegame / endgame)*

Treat serve+return, baseline rally and net finish as three phases, each with its own
heuristics and success rates, and analyze the transitions — who comes forward, and when —
rather than reporting one number per point.

## Why tennis ≠ chess

- **Stochastic and partially observable.** Transitions are probabilistic and the state is
  coarse (fatigue and exact court position are lost). Evals are empirical, never solved.
- **Short unit, huge n.** A point is ~1–10 strokes and there are ~1.85M of them, the
  opposite regime from chess. That favors frequency methods over deep search.
- **Soft legal moves.** Any stroke is possible, so no move generator is needed — the data
  is the realistic distribution.
- **No ground-truth engine.** There is no oracle for the best stroke, so "blunder" and
  "accuracy" conflate selection, execution and opponent pressure.
- **Charting bias.** Win rates inherit the coverage skew the repo documents. Report sample
  sizes; treat cross-player numbers as indicative.
