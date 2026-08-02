# Class-relative shot quality

The synthesis of the roadmap, kept deliberately small. One style-blind win-prob eval
(the graduated `match_charting_project.shots.winprob`) measures each player's decision
quality (avg win-prob conceded per stroke); we then compare each player against **what
their own style predicts** instead of against the whole field — so high-variance
stylists aren't penalized for their style, only for being worse *at* it.

### The benchmark is a surface, not a class mean

It used to be the mean of the archetype a player was sorted into. That made the metric
a step function of style, and the step moves: re-running on 0.16% less charting data
flipped 92 of 388 shot-quality verdicts, **51 of them for players whose own archetype
never changed and whose measured quality moved in the fourth decimal**. Their benchmark
had moved underneath them.

So the benchmark is now fitted smoothly over the style fingerprint (ridge on the
`player_styles` features), and a player between two archetypes gets a benchmark between
them. Under the same perturbation the flip rate falls from 24% to 5%, and the largest
single move from 2.25 standard deviations to 0.36.

How hard that model is allowed to work is the one real choice, and it isn't free:
unregularised, the fingerprint explains ~92% of the variance in shot quality and the
residual is mostly noise — the benchmark would be eating the skill it exists to measure.
λ is therefore neither a constant nor cross-validated (CV optimises prediction, which
here means *absorbing the most*). It is solved for, so the smooth benchmark accounts for
exactly as much variance as the four class means did — same degree of style control,
without the discontinuity. The two agree at +0.86 (men) / +0.81 (women).

When the optional `player_eras` table exists, quality is keyed by **era entity**, so split
careers are rated per era — e.g. Michael Chang's early grinder years and his late
big-serving years are scored against *different* archetypes (both overperform theirs).

Design rationale (why benchmark, not a per-class eval): see `../class_aware_eval` — a
class-aware eval just overfits; the rich rally state already captures style.

```bash
uv run python experiments/class_relative_wpa/run.py    # needs player_style_clusters.csv
```

## Output (ranking lists, for you to slice)

- **`reports/class_relative_wpa.csv`** — every player: `avg_wpa_lost`, `archetype`,
  `style_margin` / `style_confident` (carried through from `player_styles` — don't print
  the archetype without checking the flag), `archetype_mean` (retained for reference and
  for calibrating λ), `style_expected` (the smooth benchmark actually used),
  `class_rel_z` (<0 = better than their style predicts), `rank_overall`,
  `rank_in_archetype`.
- **`reports/class_relative_wpa.md`** — top class-relative overperformers + best-in-class.

It re-ranks the style-penalized: e.g. Lendl, Medvedev, Roddick, Davenport, Barty look
mid-pack on the raw board but top their own archetypes — skill, separated from style.

*Caveat:* the women's net/slicer archetype has only 4 players. That no longer poisons
`class_rel_z` — the smooth benchmark never divides by a four-player group's spread — but
`rank_in_archetype` and `archetype_mean` are still computed per class and are still noisy
there (`archetype_size` is in the CSV — filter on it as you like).
