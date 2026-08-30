# Class-relative shot quality

One style-blind win-prob eval (the graduated `match_charting_project.shots.winprob`)
measures each player's decision quality (avg win-prob conceded per stroke); each player is
then compared against **what their own style predicts** instead of against the whole field,
so high-variance stylists aren't penalized for their style, only for being worse *at* it.

> **This is a negative result — read "Does it measure quality?" below before using any of
> it.** The raw metric is reliable but is mostly rally length, and the correction leaves a
> residual that is mostly rally length too. Nothing here ships to the site.

### The benchmark is a surface, not a class mean

A class mean would make the metric a step function of style, and the step moves:
re-running on 0.16% less charting data flipped 92 of 388 shot-quality verdicts, **51 of
them for players whose own archetype never changed and whose measured quality moved in the
fourth decimal**. Their benchmark had moved underneath them.

So the benchmark is fitted smoothly over the style fingerprint (ridge on the
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
- **`reports/class_relative_wpa.md`** — the validation section, then top class-relative
  overperformers + best-in-class.

It re-ranks the style-penalized: e.g. Lendl, Medvedev, Roddick, Davenport, Barty look
mid-pack on the raw board but top their own archetypes.

## Does it measure quality? Mostly not

`run.py` recomputes these every run rather than fixing them in prose. All three land in
`reports/class_relative_wpa.md`:

**The raw metric is arithmetic on rally length.** WPA telescopes inside a point — the
strokes sum to (result − pre-serve value) — so the total swing per point is near-fixed
and dividing by strokes makes `avg_wpa_lost` identically *(concession per point) /
(strokes per point)*. The second factor runs it: r ≈ −0.85 with `avg_rally_len`. The raw
ranking is grinders over servebots at both ends, in both tours (Wilander, Simon, Borg,
Santoro at the top; Karlovic, Opelka, Eubanks at the bottom; Wozniacki and Sorribes Tormo
over Ostapenko and Parks). Nobody thinks that is a shot-execution ranking.

**Almost none of its spread is skill.** Split-half reliability ≈0.94 (men) / 0.93
(women) — it measures something stable. But the style fingerprint predicts 0.91 / 0.82 of
it *out-of-fold*, so the most that could be reliable non-style signal is the difference:
**0.03 / 0.11**.

**The correction's own signal is coarse.** `class_rel_z` splits half-to-half at ≈0.9,
which flatters it — λ is solved to absorb only as much variance as the class means did, so
much of the style is still inside the residual, stabilising it. Strip all the style the
fingerprint can reach and the residual splits at **0.43 (men) / 0.60 (women)**: a
three-band verdict's worth of signal, not a score's. Even that band turned out to be
mostly rally length, which is why neither figure ships.

None of this makes the class-relative comparison wrong in principle — it is the only part
of the metric with a skill claim in it. It makes the *raw* number unusable on its own, and
caps how finely the corrected one can be reported.

*Caveat:* the women's net/slicer archetype has only 4 players. The smooth benchmark never
divides by a four-player group's spread, so `class_rel_z` is unaffected, but
`rank_in_archetype` and `archetype_mean` are computed per class and are noisy there
(`archetype_size` is in the CSV).
