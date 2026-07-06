# Surface-aware match win probability

Does telling the match win-probability model *what court the match is on* make it
predict winners better than the surface-blind model already does? The production
model (`match_charting_project.winprob_match`) drives its score tree from each
player's career serve+return rates with no surface adjustment — a documented
limitation. Players plainly differ by surface (Becker's serve rate was 7.8 points
higher on hard than clay; Coric leans the other way), but the *matchup* model may
not care: both players' rates shift with the surface, and only the *relative*
shift moves a prediction. This experiment settles whether the relative shift is
big enough, and estimable enough from charted data, to pay.

## Design (a fair A/B)

One model, one knob. Both arms use the identical analytic score tree and the
identical walk-forward evaluation; the only difference is the serve/return rates
fed in:

- **Baseline** — career rates to date, shrunk toward the tour mean with
  pseudo-count `K=100` (exactly the production `walk_forward_strength` recipe).
- **Surface-aware** — the player's rates *on this match's surface* to date,
  shrunk toward their career rate with pseudo-count `k_s` (which itself shrinks
  toward the tour mean): a two-level backoff, `surface → career → tour`.
  `k_s → ∞` recovers the baseline exactly.

`k_s` is tuned on matches **before 2020** and judged once on **2020–present** —
no test-era tuning. Every prediction is pre-match (`MatchWP.pre_match()`), from
strictly earlier matches only (same-day matches are predicted before any of the
day's results update the counters).

Metrics: per-match log-loss and Brier vs the actual winner, per gender, with a
paired bootstrap CI on the log-loss difference; plus the per-surface breakdown
(clay and grass are where the signal should live — hard is most of the data and
closest to career-average conditions).

## Honest limitations

- **Charted matches only.** Rates come from the charted sample, which skews to
  TV courts and later rounds; a player's charted-clay sample is not a random
  clay sample. Surface counts are thin for most players — the backoff handles
  that, but thin history means the variant mostly *is* the baseline.
- **Surface ≠ venue.** "Hard" spans fast indoor and slow outdoor; the three-way
  label is the resolution the data supports.
- The tour-mean anchor `mu` is computed once over all data (a global constant,
  same as production) rather than walk-forward; both arms share it.

Run: `python experiments/surface_winprob/run.py` → `reports/surface_winprob.md`
+ `reports/figures/surface_winprob.png`.
