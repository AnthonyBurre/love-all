# Deep patterns: 3–4 shot sequences for the heavily-charted few

`context_length` settled that three shots of history is a net loss *on average*
— across all qualifying players, the third token adds held-out noise. But the
average is dominated by players with 5–20k strokes. Federer has 160k. This
experiment asks whether, for the ~80 players with truly extensive coverage
(≥10k charted points), there exist *individual* deep patterns solid enough to
display — and defines the bar a pattern must clear to earn that.

## The gold standard (all three, no exceptions)

A deep pattern is only interesting if the extra shot *changes the story told
by the shorter pattern inside it*. Requiring it to beat the player's base rate
would just relabel every good 2-shot trigger with a redundant third shot. So a
K-shot context earns gold only if:

1. **Beats its own parent** — its attempt rate is ≥1.3× the rate of its
   (K−1)-shot suffix, and an exact binomial test against the parent rate
   clears p < 0.005 (the parent, not the base rate, is the null).
2. **Replicates** — in each half of the player's matches (hash split) the
   context has ≥15 strokes and an attempt rate above the parent's in both.
3. **Meets the production support floor** — ≥60 strokes, ≥12 attempts overall,
   same as every displayed trigger.

Gates 1–2 multiply: a fluke that survives a p<0.005 test on the full data
still has to land above the parent in two independent halves. Patterns that
clear all three get green/trap tags from conversion exactly like production
triggers.

## Honest limitations

- Still multiple testing: a 160k-stroke player has thousands of candidate deep
  contexts. The replication gate is the real guard; the counts reported per
  player should be read as "survivors of a strict screen", not exact truths.
- Deep contexts inherit era-mixing — a 20-year career is one bag of strokes
  here. A Federer 2004 pattern and a 2015 one can blend.
- The ≥10k-point tier is charting-coverage-defined, so it skews to the
  marquee names charted across many years.

Run: `python experiments/deep_patterns/run.py` → `reports/deep_patterns.md`,
`reports/deep_patterns.csv`, `reports/figures/deep_patterns.png`.
