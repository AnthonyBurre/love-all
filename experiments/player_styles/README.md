# Player styles: fingerprint → clusters

Vectorize each player by their shot tendencies, then cluster into style archetypes.
The tennis analogue of classifying players by opening repertoire / playing style
(CROSSOVER_IDEAS #2 from the chess experiment). Consumes the graduated
`match_charting_project.shots` decoder; produces a player→archetype mapping that the
**class-relative WPA** step will use to score players against *stylistic peers*
rather than the league average.

## Approach

- **`fingerprint.py`** — one feature vector per player (≥2000 charted points) from the
  parsed strokes: serve-location lean, ace/double-fault rate, return slice% & depth,
  rally slice%, net-forwardness, forehand share, rally length, and **groundstroke**-winner
  & unforced rate. (Winners count only drive/slice shots — volley/overhead put-aways are
  already captured by net-forwardness, so net play isn't double-counted as "shotmaking".)
  Features are chosen to be roughly handedness-invariant.
- **`cluster.py`** — numpy only (no new deps): standardize → PCA (view) → k-means++ with
  restarts at a fixed **k=4** (silhouette is flat across k, so the count is a presentation
  choice); clusters described by their most extreme standardized features + nearest-centroid
  exemplars.
- **`run.py`** — per gender: fingerprint → cluster → figures + report + the mapping CSV.

```bash
uv run python experiments/player_styles/run.py
```

Writes `reports/player_styles.md`, `reports/player_style_clusters.csv`, and
`reports/figures/styles_{pca,heatmap}_{men,women}.png`.

### Career-era entities (optional `player_eras` layer)

If the `player_eras` table exists (`match-charting-project eras`), `run.py` fingerprints by
**era entity** instead of by player, so a long evolving career (e.g. *Andre Agassi
(1988–1997)* vs *(1998–2006)*) clusters as two points. Of the 34 split careers, **6 cross an
archetype boundary** — Chang (grinder → big-server), Henman (net-rusher → slice & variety),
Lendl (grinder → slice & variety), Khachanov, Kasatkina, Linette — and the report lists them.
The other 28 evolve *within* their archetype, consistent with the career-split finding that
most evolution is style-drift, not a wholesale change. Without the table it falls back to one
row per player.

## What it finds (face validity)

The archetypes line up with how fans would describe these players:

- **Men** — *Net-rusher / serve-volleyer* (Sampras, Becker, McEnroe, Henman),
  *Baseline grinder* (Djokovic, Nadal, Bautista Agut, Sinner), *Slice & variety*
  (Wawrinka, Dimitrov, Haas, Federer — one-handers and chip-and-charge), and
  *Big-serving baseliner* (Berdych, Söderling, Tsitsipas, Zverev, Medvedev — the broad
  modern-baseline group; spans aggressive shotmakers to consistent walls with a serve).
- **Women** — *Big serve / first-strike* (Krejcikova, Ivanovic, Lisicki), *Baseline
  grinder* (Jankovic, Pennetta, Stephens), *All-courter* (Swiatek, Sakkari,
  Bouchard), and a rare *Slice & net specialist* archetype (Navratilova, Niculescu,
  Tatjana Maria).

Labels describe each cluster's *centroid*; a cluster spans a range, so a borderline
player can read as the neighbouring style (e.g. Medvedev is a consistent wall who lands
among the big servers because of his serve — see the `class_rel_z` in class-relative WPA,
which correctly flags him as the steadiest of that group).

## Honest limitations

- **Style is a continuum, not species.** Silhouette scores are low (~0.11–0.14):
  players spread smoothly, so the clusters are *soft strata*, useful for stratifying,
  not hard categories. Borderline players sit between archetypes.
- **Small rare classes.** The women's net/slicer archetype is real but tiny (4 players)
  — too small to build its own eval for class-relative WPA, so that step will need to
  merge tiny classes or use soft (distance-weighted) membership.
- **Reactive features.** A player's shots are partly forced by the opponent, so a
  fingerprint is "style in context", not an intrinsic constant. Same charting-coverage
  caveat as the rest of the repo applies.

## Next: class-relative WPA

`reports/player_style_clusters.csv` (player, gender, cluster, archetype) is the bridge
to the differentiated product: fit the win-probability eval *per archetype* and measure
each player's shot quality against peers of the same style — separating skill from style,
which the league-baseline leaderboard in `chess_point_analysis` cannot.
