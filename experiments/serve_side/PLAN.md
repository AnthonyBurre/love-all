# Serve side (deuce vs ad court) — exploration plan

Status: plan only, nothing implemented. Written as a handoff; assumes no prior
context beyond this file and the repo.

## Why this matters

No analysis in this repo conditions on which court the point is served to.
That is a real gap, not a nice-to-have:

1. **Serve direction codes change meaning by side.** In the point strings,
   the first character after the serve is direction: `4` wide, `5` body,
   `6` down the T (see `src/match_charting_project/shots/notation.py:11`).
   A wide serve in the deuce court goes to a right-hander's forehand; a wide
   serve in the ad court goes to their backhand. Every serve-direction
   analysis that pools both sides is averaging over two different shots.
2. **Pressure points are not evenly distributed across sides.** Break points
   (30-40, 40-AD) are ad-court points; game points (40-0, 40-30) are deuce-court
   points; 40-15 is ad. So `experiments/score_aware_eval` and the shot_triggers
   work partially confound leverage with court side. Splitting them apart may
   change conclusions.
3. **The court visualization** being built in
   `src/match_charting_project/viz/court.py` will want to render serves on the
   correct half; the side derivation below is what it should use.

## Deriving the side

There is no side column, but it is fully determined by the score. The
`points` table in `data/tennis.duckdb` has `pts` (game score, server first,
e.g. `30-15`), `tb_set`, `svr`, `gm1`, `gm2`.

Rule: **side = deuce if the number of points already played in the game is
even, ad if odd.** Concretely:

- Regular game: map each token with `{"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4}`
  (the same `_PT` map already used in `experiments/score_aware_eval/model.py`),
  sum both tokens, `sum % 2 == 0` → deuce, else ad. This stays correct past
  deuce: 40-40 sums to 6 (deuce court), AD-40 sums to 7 (ad court).
- Tiebreak: `pts` holds integer counts (`3-2`). Same rule, sum of the two
  integers mod 2. Point one of a tiebreak (0-0) is served to the deuce court,
  then sides alternate every point, so this is exact.
- Unparseable or missing `pts` → `NA`, excluded with the count reported.
  Reuse the tiebreak-detection logic from `score_aware_eval/model.py`
  (`_is_tiebreak`) rather than writing a new one.

Sanity checks to run before trusting it (make these asserting queries or a
small test, not just eyeballing):

- Every point with `pts = '0-0'` and not in a tiebreak is deuce.
- All `30-40` and `40-AD` points come out ad; all `40-0`, `40-30`, `15-40`
  come out deuce and ad respectively per the formula.
- Overall split should be close to 50/50 with a slight deuce-court excess
  (every game starts on the deuce side). Report the actual split.

## Where the derivation should live

Add it to the parsed-points build (`src/match_charting_project/shots/build.py`)
as a `serve_side` column on `points_parsed` (values `deuce` / `ad` / `na`),
with the pure function in `src/match_charting_project/shots/notation.py` or a
sibling module so the viz code and experiments can import it directly. Tests
in `tests/` covering: regular game sequence, past-deuce scores, tiebreak,
malformed input. Do not add `from __future__ import annotations` (global
preference).

## Exploration steps, in order

Create `experiments/serve_side/` following the existing experiment layout
(`README.md` + `run.py`, see `experiments/shot_triggers/` for the shape).

**Step 1 — descriptive splits.** For each side, compute: serve-direction mix
(expect T/wide usage to differ strongly by side — this is the headline
validation that the derivation works, since it should reproduce well-known
patterns), first-serve-in rate, ace and double-fault rate, and
serve-points-won rate on first and second serve. Tour-wide first, then
per player. Per-player tables must show denominators (points charted per
side), not just rates, and filter to a minimum sample (a few hundred points
per side; align with thresholds used in the shot_triggers experiment).

**Step 2 — disentangle side from pressure.** Recompute the pressure buckets
from `experiments/score_aware_eval` within each side. The interesting
question: does a player's break-point performance look different once you
account for the fact that break points are ad-court points? Compare each
player's ad-court serve-points-won on non-pressure points vs break points —
that isolates the pressure effect from the side effect.

**Step 3 — interaction with existing shot analyses.** Re-run the
shot_triggers frequency/conversion metrics and the deep_patterns 3-4 shot
patterns split by side, for the heavily-charted players. Serve-plus-one
patterns are the most likely place a side split changes the story (the
forehand-after-wide-serve pattern only exists on one side per handedness).

**Step 4 — modeling.** Add `serve_side` as an optional component in the
score-aware win-probability model (`experiments/score_aware_eval`) the same
way `pressure` and `lead` are wired in, and evaluate whether it improves
held-out performance. Low cost given the existing component machinery.

**Step 5 — feed the viz.** Once the column exists, have the court-drawing
function in `viz/court.py` place serves in the correct service box using
`serve_side` plus direction. Note the caveat below about handedness before
labeling anything "to the forehand/backhand".

## Caveats

- **Handedness.** Wide/T mean opposite wings for a left-handed returner. The
  charting data itself does not carry handedness; if wing-level claims are
  wanted, join handedness from an external player table (there is player data
  under `src/match_charting_project/live/players.py` / `data/` worth checking
  first) or keep all claims in wide/body/T terms, which are side-relative and
  always correct.
- **Server-first score orientation.** `pts` is server-first in this dataset
  (the `_BREAK`/`_HOLD` sets in `score_aware_eval/model.py` already rely on
  this). The side formula is orientation-independent (it only uses the sum),
  but the pressure-bucket cross-tabs are not — keep using the existing sets.
- **Reporting.** Rates with denominators everywhere; plain prose in the
  README. Leave changes uncommitted for Anthony to review and commit.
