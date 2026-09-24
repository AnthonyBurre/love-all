# Shot-sequence language model

A point is a sentence in a small shot alphabet, and chess models move sequences with
n-gram opening books. This fits an order-2 Markov "opening book" over the shot tokens,
`P(next shot | last two shots)`, and reads three things off it. `player_styles` captures a
player's shot mix; this captures the order they play shots in. The last question
below consumes the graduated point eval (`match_charting_project.shots.winprob`).

## Method

- **`tokens.py`** — each stroke becomes one word. Serves are `svW/svB/svT` (wide/body/T),
  rally shots `<side><kind><dir>` (e.g. `Fd1` = forehand drive to zone 1, `Bs3` = backhand
  slice to zone 3). Coarse enough for dense statistics, fine enough to separate real
  patterns. Zones are mirrored for left-handed hitters, so a token names the shot.
- **`ngram.py`** — trigram counts smoothed by linear interpolation of trigram/bigram/
  unigram, so every continuation has nonzero probability. **Surprise** of an actual shot =
  `−log₂ P(shot | context)` in bits; **perplexity** = `2^(mean surprise)`.
- **`run.py`** — fits the *field* model (everyone) per gender, then measures each player
  against it.

```bash
uv run python experiments/shot_language/run.py
```

Writes `reports/shot_language.md` and two figures.

## What it finds

**1. Predictability**: a player's mean per-shot surprise under the field model (how far
their choices stray from tour norms). The extremes are the players you'd expect:

- *Most varied*: Moutet, McEnroe, Feliciano Lopez, Rusedski (men); Navratilova, Tatjana
  Maria, Niculescu (women): slicers, serve-volleyers, junkballers.
- *Most predictable*: Agassi, Cilic, Basilashvili (men); Osaka, Ostapenko, Davenport
  (women): flat first-strike baseliners with little slice or net play.

**2. Signature patterns**: the `(incoming → response)` shot pairs a player plays far
more than the field (lift). It finds known signatures unprompted: McEnroe's `drive →
forehand net` (≈80×, the serve-volley/ chip-charge), Navratilova's and Lopez's `drive →
backhand slice` (40–80×), Niculescu's forehand-slice junk (≈19×).

**3. Does surprise pay? No: surprise is a style, not an edge.** Binning every
non-terminal shot by its surprise and reading the mean WPA off the point eval, the
surprise↔WPA correlation is ~0 in both tours. The relationship is non-monotone: WPA peaks
at *moderate* surprise (sound, aggressive shots) and goes slightly **negative** for the
*most* unexpected shots, which are defensive scrambles rather than creative winners. So
unpredictability says who a player is, not how well they're playing.

## Limitations

- **Surprise rewards rare shot *types* as much as rare *sequencing***: a slice-heavy
  player scores "varied" largely for using uncommon shots, not only for unusual order.
- **Order-2, coarse tokens** capture local rhythm, not long-range tactics.
- **Left-handers still score higher after mirroring, and some of that is real.** Without
  the mirror, handedness alone explained 56% of the variance and every left-hander sat
  in their tour's top quartile (Connors ranked fifth-most-varied man with no slice or
  net game). Mirroring cuts it to R²=0.20 (men) / 0.14 (women), a gap of **+0.28 / +0.33
  bits**, about 1.1× the interquartile range. Part of that is real: the lefty wide serve
  in the ad court and the forehand into a right-hander's backhand are patterns an
  87%-right-handed field sees less of. Part is probably still an artifact of a
  righty-majority corpus, so a left-hander and a right-hander the same distance apart
  aren't equally unusual.
- **An era slope.** Among right-handers, bits correlate **−0.34** (men) / −0.19 (women)
  with the last season a player was charted in: the earlier the career, the more varied
  it scores. The field model pools every year in the corpus, so a player from a more
  varied era is partly being credited for their era.
- **`other` is a catch-all.** Drop shots and lobs have their own kinds and swinging
  volleys count as net shots, but trick shots and strokes the charter didn't type share
  `other`.
- The surprise↔WPA link is correlational and inherits the point eval's conflation of
  selection, execution, and pressure; same charting-coverage caveat as the rest of the
  repo.
