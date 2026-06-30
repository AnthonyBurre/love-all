# Class-relative shot quality

The synthesis of the roadmap, kept deliberately small. One style-blind win-prob eval
(the graduated `match_charting_project.shots.winprob`) measures each player's decision
quality (avg win-prob conceded per stroke); we then compare players **within their style
archetype** (from `player_styles`) instead of against the whole field — so high-variance
stylists aren't penalized for their style, only for being worse *at* it.

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
  `archetype_mean`, `class_rel_z` (<0 = beats their style's average), `rank_overall`,
  `rank_in_archetype`.
- **`reports/class_relative_wpa.md`** — top class-relative overperformers + best-in-class.

It re-ranks the style-penalized: e.g. Lendl, Medvedev, Roddick, Davenport, Barty look
mid-pack on the raw board but top their own archetypes — skill, separated from style.

*Caveat:* the women's net/slicer archetype has only 4 players, so its within-class
z-scores are noisy (`archetype_size` is in the CSV — filter on it as you like).
