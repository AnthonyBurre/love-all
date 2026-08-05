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

1. **Beats its own parent** — its aggressive shot frequency is ≥1.3× the rate of its
   (K−1)-shot suffix, and an exact binomial test against the parent rate
   clears p < 0.005 (the parent, not the base rate, is the null).
2. **Replicates** — in each half of the player's matches (hash split) the
   context has ≥15 strokes and an aggressive shot frequency above the parent's in both.
3. **Meets the production support floor** — ≥60 strokes, ≥12 aggressive shots overall,
   same as every displayed trigger.

Gates 1–2 multiply: a fluke that survives a p<0.005 test on the full data
still has to land above the parent in two independent halves. Patterns that
clear all three get green/trap tags from conversion exactly like production
triggers.

## Side heterogeneity (deuce vs ad)

The pooled gates above ignore which court the point was served to, and the
notation is side-relative in the opening — a wide serve is the same token on
both courts but a physically different serve. Discovery still stays pooled,
because halving every sample by side before mining costs more power than it
buys. Side enters as a refinement pass over the gold survivors instead: for
each one, the occurrences whose K-shot window reaches into the first four
plies (serve, return, serve+1, return+1) are split deuce/ad, and two-sided
Fisher exact tests ask whether the aggressive shot frequency or the conversion differs
between courts, Holm-corrected across every test performed. A pattern that
shows a real difference is displayed split by court; the rest keep their
pooled estimate, now with evidence that pooling is justified rather than
assumed. Mid-rally occurrences are never split — the `serve_side` model eval
showed side carries no extra signal once the rally state is known. The K≤2
openings (serve, return, and the +1 shots) live in `shot_triggers`. Full
per-side rows in `reports/deep_patterns_side.csv`.

## Honest limitations

- Still multiple testing: a 160k-stroke player has thousands of candidate deep
  contexts. The replication gate is the real guard; the counts reported per
  player should be read as "survivors of a strict screen", not exact truths.
- Deep contexts inherit era-mixing — a 20-year career is one bag of strokes
  here. A Federer 2004 pattern and a 2015 one can blend.
- The ≥10k-point tier is charting-coverage-defined, so it skews to the
  marquee names charted across many years.

Run: `python experiments/deep_patterns/run.py` → `reports/deep_patterns.md`,
`reports/deep_patterns.csv`, `reports/deep_patterns_side.csv`,
`reports/figures/deep_patterns.png`.
