# Blind re-identification: can you tell who is across the net?

Every other analysis in this repo starts from a name. It asks what Federer does, or what
the players in a style cluster do, and aggregates a whole career (or a career era) to
answer. This experiment throws the name away.

The unit here is a single **performance**: one player, in one match. Strip the identity,
turn the performance into a vector of shot tendencies, and ask whether the vector still
points back at the human who produced it. If it does, players have signatures that
survive a change of opponent, surface and decade. If it doesn't, "playing style" is
mostly a career-average artifact that dissolves the moment you look at one afternoon. Put
the other way: do some players' performances resemble *each other* more than they resemble
their own showing from a few years earlier? That asks whether identity or era dominates.

## The serve is quarantined on purpose

The obvious way to name an opponent is from their delivery. So the features come in
blocks that are scored separately, and the serve is kept out of the one that matters:

| block | what it sees |
|---|---|
| `serve` | direction by court side (deuce/ad), first-serve rate, ace, double fault, unreturned |
| `return` | the return of serve: slice vs drive, depth, direction, made-return rate |
| `rally` | strokes 3+: forehand share, slice, net play, direction, how points end, tempo |
| `response` | `return` + `rally`, so everything you could observe from the far baseline |
| `all` | every feature |

`response` is the interesting one. It is what comes back at you once the point is live,
with nothing about how the point started.

## Method

`features.py` builds one row per (match, player) from the decoded notation, reusing the
graduated `match_charting_project.shots` decoder and the deuce/ad derivation in
`shots/score.py`. `reid.py` scores it. Two numbers:

- **Verification AUC**: over pairs of performances, the chance a same-player pair sits
  closer together than a different-player pair. 0.5 is chance. Preferred as the headline
  because it needs no baseline correction and survives pair filtering, which is what all
  the controls do.
- **Rank-1 accuracy**: is a performance's nearest neighbour the same player? Reported
  against its own chance rate, which is not 1/n_players since it depends on how many
  other performances each player has, so it is computed per query and averaged.

Three choices do the real work of keeping the number honest.

**The metric is fit on different players than it is scored on.** Raw z-scored Euclidean
distance would treat a feature that swings wildly between one player's own matches
(unforced-error rate) as equal evidence to one that barely moves. So distances are
whitened by the pooled *within-player* covariance, which shrinks the directions a single
player rattles around in and stretches the ones that separate people. That covariance is
estimated on one half of the players and every score is computed on the other half, so no
performance is ever identified by a metric that was shown that player's own scatter.

**Performances are capped at 30 per player.** Uncapped, Federer's 700+ charted matches
alone would supply about 23% of every same-player pair in the men's draw, and the headline
would mostly be a statement about one player.

**Rates are conditioned on charted denominators.** Depth shares are computed over returns
whose depth was actually charted, direction shares over strokes with a charted direction.
Charters vary in how much detail they record, so an unconditioned rate would partly
measure the charter. This is the confound most likely to fake a result here, and it gets
its own check: asking the same vectors to identify the **charter** instead of the player
lands at AUC 0.54, near chance.

Same-match pairs are excluded everywhere. Two performances from one match share the rally,
so their similarity is the match rather than the player. Men and women are scored
separately, since cross-gender pairs would be trivially separable.

## What it found

Full write-up with tables and figures: [`reports/blind_reid.md`](../../reports/blind_reid.md).
Regenerate with `python experiments/blind_reid/run.py`.

**You can tell, and the serve is not how.** The `response` block reaches AUC 0.685 (men)
and 0.672 (women) on held-out players, beating the `serve` block's 0.643 outright. The
rally strokes alone (11 features, no serve, no return) reach 0.677. Rank-1 accuracy on
`response` is 0.109 against a 0.0055 chance rate, about 20x chance, from one match, with
the serve withheld and against a gallery of every other held-out performance. The hunch
that the serve would be the primary tell is backwards: of the three views it is the
weakest. Read that as a statement about *charted* serve data, though. The notation records
direction, in-rate and outcome, not speed or spin or toss.

**The fingerprint is net play and slice, not placement.** Ranked by single-feature AUC,
the top six are all response features: net-stroke rate, return slice, rally slice,
net-approach rate, forehand share, rally tempo. Court-zone directions come last, barely
above chance. Where the ball went says much less about who chose to hit it there than how
they chose to hit it.

**A player is their own nearest kind, but the signature does fade.** Only about 1% of
held-out men (5% of women) sit further from their own other performances than from the
field's, so on the direct comparison identity wins easily. Time is a different story.
Scored inside each year-gap band, men's AUC falls from 0.670 for pairs in the same season
to 0.620 at six to nine years apart, giving up roughly a third of the lift above chance.
Still clearly recognisable, measurably less reliably. That agrees with `career_splits`
rather than cutting against it, and puts a rate on the drift.

Two traps, both spelled out in the report. The ten-plus band rebounds, which is
survivorship rather than recovery: only decade-spanning careers are in it, and era
separation spreads the different-player pairs too. And a *cumulative* "6+ years apart" cut
reads much flatter (0.678) than the six-to-nine band, because pooling gap bands mixes
distance scales and inflates the pooled AUC. Per-band is the number to trust.

**The crossings are real but rare, and concentrated.** A handful of different-player pairs
do sit closer to each other than to either player's own other showings. The report lists
them, and one name (Jason Kubler) takes 9 of the 10 men's slots, so read the list as a few
stylistically fluid players rather than as many mutual look-alikes. The criterion uses the
*smaller* of the two self-distances, deliberately: taking the larger lets one erratic
player pair "confusably" with half the tour, which says nothing about mutual similarity.

**What limits accuracy is sample size, not the strength of the signal.** Split held-out
performances into quartiles by charted points and men's rank-1 rises from 0.050 to 0.125.
The women's series is noisier and not monotone, so this is clear for the men and only
directional for the women. A rate from a 90-point match is mostly sampling noise; the same
rate over a five-setter is a measurement.

## Limits

- A high AUC narrows the field, it does not name a human. Two players with genuinely
  similar games stay confusable no matter how much data is added.
- What a player hits back is partly the opponent's doing. The different-opponent control
  shows this is not the main driver, but `avg_rally_len` is a property of the match rather
  than of either player, kept because tempo is also a real trait.
- The field spans 1960 to 2026 and pre-1990 matches are sparse and differently charted.
  Some players with wide own-spread are being measured across an era gap, not caught
  being inconsistent. Guillermo Vilas is the extreme case and the report flags him.
- Charting coverage skew is inherited from the whole repo. Later rounds and bigger names
  are charted more, so the player mix is not the tour's.

## Files

| file | what it does |
|---|---|
| `features.py` | per-performance vectors, the three feature blocks, parquet cache |
| `reid.py` | the metric (standardize + within-player whitening), AUC, rank-1, pair controls |
| `run.py` | scores both tours, writes the report, CSVs and five figures |
