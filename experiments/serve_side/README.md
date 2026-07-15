# Serve side: deuce vs ad court

Nothing else in this repo conditions on which court a point is served to, and
that turns out to hide real structure. The serve-direction codes mean opposite
wings on the two sides: a wide serve in the deuce court goes to a right-hander's
forehand, a wide serve in the ad court goes to their backhand. Any
serve-direction number that pools both sides is averaging two different shots.
Leverage is lopsided too. Break points cluster in the ad court, game points in
the deuce court, so a score-aware read that ignores the side partly confounds
pressure with court.

## Deriving the side

There is no side column, but the score fixes it. Every game and every tiebreak
opens on the deuce court, then the side alternates with each point, so the side
is just the parity of how many points have already been played:

    side = deuce if (points already played) is even, else ad

The count of points played is the sum of the two score tokens — `0/15/30/40/AD`
mapped to `0/1/2/3/4` for a normal game, or the raw integers for a tiebreak. The
rule lives in `src/match_charting_project/shots/score.py` as `serve_side(pts)`
and is materialized as a `serve_side` column on `points_parsed`. It reads the
token type rather than a separate tiebreak test, which keeps it correct for the
~9k advantage-set points still scored 15/30/40 past 6-6. Across the 1.85M
charted points the split is 52.2% deuce / 47.8% ad — the slight deuce excess
every game opening on that side predicts, and nothing derives as unknown.

## What the run reports

`python experiments/serve_side/run.py` writes `reports/serve_side.md`, three
CSVs, and a figure. Three steps:

**Step 1 — descriptive splits.** Per side, tour-wide and per heavily-charted
player (both sides shown with their point denominators): first-serve direction
mix, first-serve-in rate, ace and double-fault rate, and serve-points-won on the
first and second serve. The direction mix is the headline validation. It
reproduces the well-known pattern without being told it: men serve wide 51% of
the time in the ad court against 44% in the deuce court, and down the T 46%
against 40%. Left-handers invert it — Nadal serves wide 54% of the time in the
ad court against 30% in the deuce court, the mirror image, which is exactly what
a correct derivation should produce.

**Step 2 — side vs pressure.** The same leverage buckets from `score_aware_eval`,
but computed within each side, so pressure varies while the court is held fixed.
Tour-wide the server wins about 3 points per hundred fewer on break points than
on normal points, and that gap is close to the same size in both courts. The
break-point penalty is a pressure effect, not a side effect dressed up as one.
Note that break points are not purely ad-court: `15-40` and `0-40` fall on
opposite sides, so consecutive break points in a game alternate courts. That is
the confound this step exists to separate.

**Step 3 — serve+1.** The forehand share and attempt rate of the server's first
groundstroke, split by side, since serve-plus-one is where a side split is most
likely to move. Nadal's serve+1 is a forehand 75% of the time in the deuce court
and 80% in the ad court, and he converts those ad-court attempts at 60% against
49% in the deuce court — the left-handed forehand-plus-one off the ad-court
serve, visible only once the side is separated out. Claims here stay in
server-wing and wide/body/T terms, which are side-relative and always correct
without assuming the returner's handedness.

## Honest limitations

- **Direction mix mixes serves.** Step 1's mix is over first-serve targets that
  were charted; serves with an unknown target are dropped from the mix but kept
  in every other rate.
- **Handedness is not joined.** Wide and T mean opposite wings for a left-handed
  returner, so this experiment never translates a serve target into "to the
  forehand". All wing-level statements are about the server's own charted wing.
- **Conversion is context-selected.** Comparing a player against themselves
  across sides is fair; comparing serve+1 conversion across players also carries
  shot selection and opposition.

Run: `python experiments/serve_side/run.py` → `reports/serve_side.md`,
`reports/serve_side.csv` (+ `_pressure`, `_serveplus1`),
`reports/figures/serve_side.png`.
