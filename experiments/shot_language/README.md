# Shot-sequence language model

A point is a sentence in a small shot alphabet; chess people model move sequences with
n-gram opening books and move-prediction models. This ports that idea: an order-2 Markov
"opening book" over the shot tokens — `P(next shot | last two shots)` — and reads three
things off it. It's the *sequential* complement to `player_styles`, which captured a
player's *static* shot mix; this captures the order they play shots in.

The next unbuilt crossover from `chess_point_analysis/CROSSOVER_IDEAS.md`, and it consumes
the graduated point eval (`match_charting_project.shots.winprob`) for the last question.

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

## What it finds (and it's face-valid)

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

## Honest limitations

- **Surprise rewards rare shot *types* as much as rare *sequencing*** — a slice-heavy
  player scores "varied" largely for using uncommon shots, not only for unusual order.
- **Order-2, coarse tokens** — captures local rhythm, not long-range tactics; zones are
  the raw codebook 1/2/3.
- The surprise↔WPA link is correlational and inherits the point eval's conflation of
  selection, execution, and pressure; same charting-coverage caveat as the rest of the repo.
