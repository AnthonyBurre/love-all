# Player styles: fingerprint → clusters

Describe each player by their shot tendencies, then cluster them into style archetypes:
the tennis version of classifying chess players by opening repertoire
(CROSSOVER_IDEAS #2). It uses the `match_charting_project.shots` decoder and produces a player →
archetype mapping.

## Approach

- **`fingerprint.py`** — one feature vector per player (≥2000 charted points) from the
  parsed strokes: serve-location lean, ace and double-fault rate, return slice % and
  depth, rally slice %, net-forwardness, forehand share, rally length, and
  **groundstroke** winner and unforced error rates. Winners count only drives and
  slices, since volley and overhead put-aways are already in net-forwardness. Features
  are chosen to be roughly handedness-invariant.
- **`cluster.py`** — numpy only. Standardize, PCA (for the view), then k-means++ with
  restarts at a fixed **k=4**. Each cluster is described by its most extreme
  standardized features and the players nearest its centroid. Silhouette is flat for k
  **≥ 3**, so among those the count is a presentation choice (see the limitation on k
  below).
- **`run.py`** — per gender, fingerprint → cluster → figures, report and mapping CSV.

```bash
uv run python experiments/player_styles/run.py
```

Writes `reports/player_styles.md`, `reports/player_style_clusters.csv`, and
`reports/figures/styles_{pca,heatmap}_{men,women}.png`.

### Career-era entities (optional `player_eras` layer)

If the `player_eras` table exists (`match-charting-project eras`), `run.py` fingerprints
by **era entity** instead of by player, so a career that changed (e.g. *Andre Agassi
(1988–1997)* and *(1998–2006)*) clusters as two points. Of the 35 split careers, **5
cross an archetype boundary**: Bublik (net-rusher → big-serving baseliner), Khachanov
(big-serving baseliner → grinder), Chang (grinder → big-serving baseliner), Kasatkina
(grinder → baseline all-rounder) and Pegula (baseline all-rounder → grinder). The other
30 change within their archetype, consistent with the career-split finding that most
change is drift, not a new style. Without the table it uses one row per player.

The crossing players are by construction the ones nearest a boundary, which is exactly
where the confidence gate below applies, so these names move between rebuilds.
`reports/player_styles.md` has the current list.

## What it finds

The archetypes match how fans would describe these players:

- **Men** — *Net-rusher / serve-volleyer* (Sampras, Becker, McEnroe, Henman), *Baseline
  grinder* (Djokovic, Nadal, Bautista Agut, Sinner), *Slice & variety* (Wawrinka,
  Dimitrov, Haas, Federer: one-handers and chip-and-charge), and *Big-serving baseliner*
  (Berdych, Söderling, Tsitsipas, Zverev, Medvedev), the broad modern baseline group,
  from aggressive shotmakers to consistent players with a big serve.
- **Women** — *Big serve / first-strike* (Krejcikova, Ivanovic, Lisicki), *Baseline
  grinder* (Jankovic, Pennetta, Stephens), *Baseline all-rounder* (Swiatek, Sakkari,
  Bouchard), and a rare *Slice & net specialist* (Navratilova, Niculescu, Tatjana
  Maria).

*Baseline all-rounder* is the fallback label: the players no earlier rule described. It
isn't called *All-courter* because this group's net rate is slightly *below* average.

Labels describe each cluster's *centroid*. A cluster spans a range, so a borderline
player can look like the neighbouring style: Medvedev is a consistent baseliner who
lands among the big servers because of his serve.

## Limitations

- **Style is a continuum.** Silhouette scores are low (~0.11–0.14): players spread
  smoothly, so the clusters are soft strata, useful for grouping but not hard
  categories.
- **The geometry supports two groups, not four.** Silhouette on the shipped
  fingerprints:

  | | k=2 | k=3 | k=4 | k=5 | k=6 |
  |---|---|---|---|---|---|
  | Men (n=242) | **0.362** | 0.134 | 0.136 | 0.131 | 0.122 |
  | Women (n=152) | **0.506** | 0.151 | 0.117 | 0.112 | 0.115 |

  The one split the data supports strongly is two-way: net-rushers against everyone else
  for the men, slicers against everyone else for the women. For the women k=4 scores
  *below* k=3. Four archetypes are kept because they match how the sport talks about
  style, and because `style_confident` withholds any label whose margin is too thin.
  Four does split up the women's most distinctive group: of the twelve players whose
  fingerprints are slice-dominated, eight are labelled *Baseline grinder /
  counterpuncher* (Hingis, Radwanska, Evert, Mauresmo and Sanchez Vicario among them),
  and Barty lands in *Big serve / first-strike* by a margin of 0.004.
- **Small rare classes.** The women's net/slice archetype is real but has only 4
  players.
- **Reactive features.** A player's shots are partly forced by the opponent, so a
  fingerprint is style in context, not a constant. The repo's charting-coverage caveat
  also applies.
- **`avg_rally_len` is not adjusted for surface, era or opponent**, and the site prints
  it as a figure of its own. Charted points average **5.20** strokes on clay, **4.69**
  on hard and **4.02** on grass: a 1.18-stroke spread, against a between-player
  interquartile range of 0.80. Era moves it too, without a trend: **4.21** in the 1990s
  against 4.88 in the 1980s and about 4.8 from 2000 on. A point's length is shared by
  both players, so part of any player's figure comes from their opponents.

  None of this affects the clustering, which only needs a common axis. It does affect the
  shipped figure, and the panel's key says so.

## What the fingerprint feeds

`reports/player_style_clusters.csv` has player, gender, cluster, archetype,
`style_margin`, `style_confident`, and the fingerprint features.

It was meant to feed a per-player skill verdict (shot quality against what a player's
style predicts). That didn't work at this resolution; `../class_relative_wpa` has the
numbers.

The site uses only the archetype line, and only where `style_confident` holds.
`style_margin` is the per-entity silhouette (how much better the player's own archetype
fits than the next best), and `style_confident` compares it with `CONFIDENT_MARGIN`.

Re-running on 0.16% less charting data moved 57 of 388 archetype labels, and 56 of those
57 belonged to players whose own fingerprint hadn't changed: the k-means centroids moved
under them. Those players had a median margin of 0.02, against 0.14 for the labels that
held. Withholding labels below the threshold cuts instability among the labels still
shown from 15% to about 2% under the same perturbation.

Consumers should respect the flag rather than read `archetype` directly; the site prints
"Between styles" below it. Nothing downstream should benchmark against a cluster mean (see
`../class_relative_wpa`).
