# Form and streakiness in match win probability

Does telling the match win-probability model *how a player has been playing
lately* improve its predictions — and does it help more for players who are
individually **streaky** (whose good and bad patches persist) than for players
whose fluctuations are just noise? The production model uses career-to-date
serve+return rates: a player's June is weighed the same as their rookie year,
and a hot streak is invisible. This experiment asks whether "form" is real
enough in charted data to pay, in two steps that separate two claims usually
conflated:

1. **Form** — does a player's recent performance *relative to expectation*
   predict their next match at all (uniform weight for everyone)?
2. **Streakiness** — is there stable individual variation in how much recent
   patches persist, and does weighting form by each player's own streakiness
   beat the uniform weight?

## Design

**The form signal.** After every charted match, each player gets a residual:
their observed share of total points won minus the share the baseline model
expected pre-match (so it's opponent-adjusted — beating a better opponent than
expected counts as form even in a loss). A player's *form* entering a match is
the shrunk mean of their last 10 residuals within the previous 18 months
(pseudo-count 5, so one hot match moves it little).

**The A/B (one knob).** Both arms use the identical score tree and walk-forward
discipline. The form arm shifts the matchup point-win probabilities by
`w · (form₁ − form₂)`, symmetrically. `w` is tuned on pre-2020 matches, judged
once on 2020+.

**The streaky arm.** Each player's streakiness is the lag-1 autocorrelation of
their residual sequence over the *training era only*, restricted to pairs of
charted matches ≤45 days apart (charted matches are sparse; a "next match" six
months later says nothing about persistence), shrunk toward zero by sample
size. The streaky arm scales each player's form weight by their own
streakiness multiplier and is evaluated **only on the test era** (its
per-player parameter is fit on the whole training era, so scoring it on train
would leak). It inherits `w` from the uniform tuning — no extra test-era knob.

**Diagnostics before verdicts.** Two model-free checks that don't depend on
the score tree: (a) does form-entering-a-match predict the *realized residual*
of that match (decile plot + slope)? (b) is the distribution of per-player
autocorrelations distinguishable from a within-player permutation null?

## Honest limitations

- **Charted matches are a sparse, biased sample of a season.** Consecutive
  charted matches can be months apart, and charting skews to TV courts and
  later rounds — a player's charted "recent matches" over-sample their wins at
  big events. Real week-to-week form may exist and be invisible here; this
  experiment answers what *charted* data supports, which is what the site can
  actually use.
- Residuals are in total-points-share units, conflating serve and return form;
  a finer split doubles the parameters on the same thin histories.

Run: `python experiments/form_streakiness/run.py` →
`reports/form_streakiness.md` + `reports/figures/form_streakiness.png`.
