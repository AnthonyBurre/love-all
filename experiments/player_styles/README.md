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
  restarts at a fixed **k=4**; clusters described by their most extreme standardized features
  + nearest-centroid exemplars. Silhouette is flat across k **≥ 3**, so among those the count
  is a presentation choice — see the limitation on k below.
- **`run.py`** — per gender: fingerprint → cluster → figures + report + the mapping CSV.

```bash
uv run python experiments/player_styles/run.py
```

Writes `reports/player_styles.md`, `reports/player_style_clusters.csv`, and
`reports/figures/styles_{pca,heatmap}_{men,women}.png`.

### Career-era entities (optional `player_eras` layer)

If the `player_eras` table exists (`match-charting-project eras`), `run.py` fingerprints by
**era entity** instead of by player, so a long evolving career (e.g. *Andre Agassi
(1988–1997)* vs *(1998–2006)*) clusters as two points. Of the 35 split careers, **5 cross an
archetype boundary** — Bublik (net-rusher → big-serving baseliner), Khachanov (big-serving
baseliner → grinder), Chang (grinder → big-serving baseliner), Kasatkina (grinder → baseline
all-rounder), Pegula (baseline all-rounder → grinder) — and the report lists them. The other 30
evolve *within* their archetype, consistent with the career-split finding that most evolution is
style-drift, not a wholesale change. Without the table it falls back to one row per player.

The crossing set is by construction the entities nearest a boundary — exactly the population the
confidence gate below exists to distrust — so these names move between rebuilds. Read the list
as the shape of the result; `reports/player_styles.md` is the authority.

## What it finds (face validity)

The archetypes line up with how fans would describe these players:

- **Men** — *Net-rusher / serve-volleyer* (Sampras, Becker, McEnroe, Henman),
  *Baseline grinder* (Djokovic, Nadal, Bautista Agut, Sinner), *Slice & variety*
  (Wawrinka, Dimitrov, Haas, Federer — one-handers and chip-and-charge), and
  *Big-serving baseliner* (Berdych, Söderling, Tsitsipas, Zverev, Medvedev — the broad
  modern-baseline group; spans aggressive shotmakers to consistent walls with a serve).
- **Women** — *Big serve / first-strike* (Krejcikova, Ivanovic, Lisicki), *Baseline
  grinder* (Jankovic, Pennetta, Stephens), *Baseline all-rounder* (Swiatek, Sakkari,
  Bouchard), and a rare *Slice & net specialist* archetype (Navratilova, Niculescu,
  Tatjana Maria).

The *Baseline all-rounder* label is the cascade's else-branch and is named to say so: players
there are the ones no earlier branch described, not players found to play all-court tennis. It
is deliberately not *All-courter*, a claim about court coverage and net play that this centroid
does not support — its net rate is slightly *below* average — on the largest asserted women's
group.

Labels describe each cluster's *centroid*; a cluster spans a range, so a borderline
player can read as the neighbouring style — Medvedev is a consistent wall who lands among the
big servers because of his serve.

## Limitations

- **Style is a continuum, not species.** Silhouette scores are low (~0.11–0.14):
  players spread smoothly, so the clusters are *soft strata*, useful for stratifying,
  not hard categories. Borderline players sit between archetypes.
- **The geometry supports two groups, not four.** Measured on the shipped fingerprints,
  silhouette runs:

  | | k=2 | k=3 | k=4 | k=5 | k=6 |
  |---|---|---|---|---|---|
  | Men (n=242) | **0.362** | 0.134 | 0.136 | 0.131 | 0.122 |
  | Women (n=152) | **0.506** | 0.151 | 0.117 | 0.112 | 0.115 |

  The single split the data insists on is two-way — net-rushers against everyone else for
  the men, slicers against everyone else for the women — and for the women k=4 scores
  *below* k=3. Four archetypes are kept because they match how the sport talks about
  itself and because `style_confident` withholds any label whose margin is too thin to
  trust; that gate is what makes a k the geometry does not pin down defensible to ship.
  Forcing four does shatter the women's most distinctive cohort: of the twelve players
  whose fingerprints are slice-dominated, eight are asserted *Baseline grinder /
  counterpuncher* (Hingis, Radwanska, Evert, Mauresmo, Sanchez Vicario among them), and
  Barty lands in *Big serve / first-strike* on a margin four thousandths over the line.
- **Small rare classes.** The women's net/slicer archetype is real but tiny (4 players)
  — too small to build its own eval for class-relative WPA, so that step will need to
  merge tiny classes or use soft (distance-weighted) membership.
- **Reactive features.** A player's shots are partly forced by the opponent, so a
  fingerprint is "style in context", not an intrinsic constant. Same charting-coverage
  caveat as the rest of the repo applies.
- **`avg_rally_len` is unadjusted for surface, era and opponent**, and it is the one
  feature the site also prints as a figure in its own right ("shots per point"). Charted
  points average **5.20** strokes on clay, **4.69** on hard and **4.02** on grass — a
  1.18-stroke spread against a between-player interquartile range of 0.80, so where a
  career was charted moves the number by more than half the tour's own middle. Era does
  the same without being a trend: the 1990s average **4.21** against 4.88 in the 1980s and
  a flat ~4.8 from 2000 on, so the fast-court serve-volley years read as a dip rather than
  as one end of a slope. And because a point has one length shared by both players, part
  of any figure belongs to who that player was drawn against.

  None of this hurts the clustering, which only needs entities placed on a common axis.
  It matters for the shipped figure, where the panel's key states it.

## What the fingerprint feeds

`reports/player_style_clusters.csv` carries player, gender, cluster, archetype,
`style_margin`, `style_confident`, and the fingerprint features themselves.

It was meant to feed a per-player skill verdict — shot quality measured against what a
player's style predicts. That did not work; `../class_relative_wpa` has the arithmetic. The
fingerprint is still the right object, but it could not support a skill verdict at this
resolution.

What the clusters do feed into the site is the archetype line itself, and only where
`style_confident` holds.

Two columns exist because the label is softer than it looks. `style_margin` is the
per-entity silhouette — how much better this player's own archetype fits than the
next-best one — and `style_confident` is that against `CONFIDENT_MARGIN`.

They earn their place empirically. Re-running on 0.16% less charting data moved 57 of
388 archetype labels, and 56 of those 57 belonged to players whose own fingerprint had
not changed at all: k-means centroids shifted underneath them. The entities that moved
had a median margin of 0.02 against 0.14 for the ones that held, so the margin predicts
the churn sharply, and withholding the name below the threshold takes label instability
among *asserted* archetypes from 15% to none across that same perturbation.

Consumers are expected to respect the flag rather than take `archetype` at face value —
the site prints "Between styles" below it. Nothing downstream should benchmark against a
cluster mean; see `../class_relative_wpa` for why.
