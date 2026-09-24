# Match win probability: the score-tree layer

The point eval (`chess_point_analysis`) answers *"how is this rally going?"*: P(server
wins **the point**) from the rally state. This experiment adds the layer above it,
answering *"how is the match going?"*: P(a player wins **the match**) from the score,
plus the **leverage** of each point (how much it can swing the match). It uses the point
eval rather than replacing it.

## Why an analytic model

The `score_aware_eval` experiment found that conditioning the point eval on the score
does **not** improve it: points are close to independent given the server (the
Klaassen–Magnus result). That is the assumption that makes an analytic score tree exact.
If each player wins points on serve at a fixed rate, win probability propagates point →
game → set → match in closed form, so two numbers go up the tree instead of another
fitted table.

## Inputs

- **Matchup strength** is the only free parameter: `p1`, `p2`, each player's probability
  of winning a point on their own serve *against this opponent*. It combines the
  player's **serve** rate and the opponent's **return** rate around the league mean
  (`serve_A − return_B + (1 − μ)`), so an elite returner pulls the server's number down.
  `μ` is the league serve-win rate, the same quantity the point eval's `base()`
  converges to.
- **No leakage.** Rates are estimated **walk-forward**: a match is scored only from
  matches played strictly earlier, so the calibration below is out of sample. The cost
  is that a player with little prior charting shrinks toward the league mean (an even
  matchup), so early and sparse matches are less sharply separated.
- **Leverage links back to shot quality.** The point eval scores each shot's WPA in
  point-win units; multiplying by the point's leverage converts it to match-win units. A
  mistake on a swing point costs far more than the same shot at 40-0.

The score tree is a classical tennis model, not a chess one (chess has no nested scoring).
Its only input is the scalar `p1/p2`, so any strength model plugs into the same
`MatchWP(p1, p2, …)`. The chess crossover is the layer on top: leverage-weighted shot
quality.

## The model (`winprob_match.py`)

`MatchWP(p1, p2, best_of)`, with memoized recursions and closed forms over standard
scoring:

- **game** — closed form, with the deuce geometric series `g²/(g²+(1−g)²)`.
- **tiebreak** — recursion over the 1-2-2 serve rotation, with a tiebreak-deuce closed
  form.
- **set** — recursion over games using each player's hold probability; 7-point tiebreak
  at 6-6 (overridable, so the 2019 Wimbledon final's 12-12 tiebreak comes out exactly).
- **match** — best-of-3 or -5 over sets.

`wp(score)` gives the live number at any point, and `leverage(score)` = `wp(win the
point) − wp(lose the point)`. Two approximations, each worth under 0.1% WP: the first
server of a new set follows the previous set's alternation, and non-standard historical
final-set rules default to the 6-6 tiebreak.

## Validation

1. **Internally exact** — it satisfies the martingale identity `WP = P(win pt)·WP(after
   win) + P(lose pt)·WP(after lose)` to **~2e-16** over 40k random states (best-of-3 and
   -5).
2. **Calibrated against real outcomes** — model WP at every point against the eventual
   winner tracks the diagonal across all deciles (log-loss 0.532 men, 0.544 women,
   against 0.693 for a coin flip). Strength is walk-forward, so this is out of sample.
   The slight under-confidence at the extremes comes from shrinking thin-history players
   toward an even matchup.
3. **Face-valid on a marquee match** — the 2019 Wimbledon final, below.

## What it finds

![curve](../../reports/figures/match_winprob_curve.png)

Federer's win probability peaks at **98.8%** serving at 8-7, 40-15 in the fifth (two
championship points), then falls as Djokovic saves them and wins the deciding tiebreak. It
stays under 99% because the model credits Djokovic's return.

In the leverage panel, **the championship points are *low* leverage**: Federer was already
near 99%, so the match barely moves on them. The highest-leverage points are the close
fifth-set break points. Leverage measures how much a point can swing the match, not how
dramatic it looks. Scaling the point eval's shot WPA by leverage ranks the match's biggest
match-WP swings.

```bash
uv run python experiments/match_winprob/run.py
```

Writes `reports/match_winprob.md`, `reports/figures/match_winprob_calibration.png`, and
`reports/figures/match_winprob_curve.png`.

## Limitations

- **Strength is serve and return only.** It is walk-forward and matchup-aware, but has
  no surface, form, fatigue or recency weighting, and thin-history players fall toward
  an even matchup.
- **Independent points** are a good approximation (per `score_aware_eval`), not an exact
  one, which is part of why calibration isn't perfect.
- **Charting bias** — the same coverage caveat as the rest of the repo. Leverage-weighted
  shot quality also inherits the point eval's mixing of selection, execution and
  pressure.

## Richer matchup strength

A better `p1/p2` input plugs in without changing the tree or the leverage layer. Two
candidates came back negative: surface-specific rates (`../surface_winprob`) and
recency/form weighting (`../form_streakiness`). Opponent-adjusted ratings, external
covariates (ranking, fatigue, conditions) and a learned strength model are untried.
