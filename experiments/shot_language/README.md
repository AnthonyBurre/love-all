# Shot-sequence language model

A point is a sentence in a small shot alphabet; chess people model move sequences with
n-gram opening books and move-prediction models. This ports that idea: an order-2 Markov
"opening book" over the shot tokens — `P(next shot | last two shots)` — and reads three
things off it. It's the *sequential* complement to `player_styles`, which captured a
player's *static* shot mix; this captures the order they play shots in. The last question
below consumes the graduated point eval (`match_charting_project.shots.winprob`).

## Method

- **`tokens.py`** — each stroke → one word: serves as `svW/svB/svT` (wide/body/T), rally
  shots as `<side><kind><dir>` (e.g. `Fd1` = forehand drive to zone 1, `Bs3` = backhand
  slice to zone 3). Coarse enough for dense statistics, fine enough to separate real
  patterns. Court zones are the codebook's raw 1/2/3 (not relabelled crosscourt/line,
  which would need handedness).
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

**1. Predictability** — a player's mean per-shot surprise under the field model (how far
their choices stray from tour norms). The extremes are exactly who you'd name:

- *Most varied*: Moutet, McEnroe, Feliciano Lopez, Rusedski (men); Navratilova, Tatjana
  Maria, Niculescu (women) — slicers, serve-volleyers, junkballers.
- *Most predictable*: Agassi, Cilic, Basilashvili (men); Osaka, Ostapenko, Davenport
  (women) — flat first-strike baseliners with little slice/net in the mix.

**2. Signature patterns** — the `(incoming → response)` shot pairs a player plays far more
than the field (lift). This is the tactical-motif analogue, and it rediscovers real
signatures automatically: McEnroe's `drive → forehand net` (≈80×, the serve-volley/
chip-charge), Navratilova's and Lopez's `drive → backhand slice` (40–80×), Niculescu's
forehand-slice junk (≈19×).

**3. Does surprise pay? No — surprise is a *style*, not an *edge*.** Binning every
non-terminal shot by its surprise and reading the mean WPA off the point eval, the
surprise↔WPA correlation is ~0 in both tours. The relationship is non-monotone: WPA peaks
at *moderate* surprise (sound, aggressive shots) and goes slightly **negative** for the
*most* unexpected shots — those are defensive, forced gets, not creative winners. So
unpredictability differentiates *who a player is*, not *how well they're playing*.

## Limitations

- **Surprise rewards rare shot *types* as much as rare *sequencing*** — a slice-heavy
  player scores "varied" largely for using uncommon shots, not only for unusual order.
- **Order-2, coarse tokens** — captures local rhythm, not long-range tactics. Zones are
  the codebook's 1/2/3, mirrored for left-handed hitters (see `tokens.py`) so a token
  names the shot rather than the half of the court it landed in.
- **A residual left-hander premium survives the mirror, and some of it is real.** Before
  the mirror, handedness alone explained 56% of the variance and every left-hander in the
  corpus sat in the top quartile of their tour — Connors ranked fifth-most-varied man with
  no slice game and no net game, which was the tell. Mirroring cuts that to R²=0.20 (men)
  / 0.14 (women), leaving a gap of **+0.28 / +0.33 bits**, or about 1.1× the interquartile
  range. Part of that is genuine: the lefty serve out wide in the ad court and the forehand
  into a right-hander's backhand really are patterns an 87%-right-handed field model sees
  less of, and a model of the field is the right thing to be surprised relative to. Part of
  it is probably still an artifact of a righty-majority corpus. The figure should not be
  read as if a left-hander and a right-hander an equal distance apart are equally unusual.
- **An era slope.** Among right-handers, bits correlate **−0.34** (men) / −0.19 (women)
  with the last season a player was charted in: the earlier the career, the more varied it
  scores. The field model pools every year in the corpus, so a player from a more varied
  era is partly being credited for their era.
- **Drop shots, lobs and swinging volleys share one token.** `kind` collapses to
  drive/slice/net/other, and `other` holds all three — so the shots a tennis person would
  call the most inventive are the ones the alphabet distinguishes least.
- The surprise↔WPA link is correlational and inherits the point eval's conflation of
  selection, execution, and pressure; same charting-coverage caveat as the rest of the repo.
