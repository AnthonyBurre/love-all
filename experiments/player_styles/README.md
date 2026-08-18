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
  is a presentation choice — see the note on k below, which corrects an earlier claim that it
  was flat across k generally.
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

These names move between rebuilds and this paragraph has been stale before: the crossing set is
by construction the entities nearest a boundary, which is exactly the population the confidence
gate below exists to distrust. `reports/player_styles.md` is regenerated on every run and is the
authority; treat this list as an illustration of the shape, not a fixed finding.

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

The *Baseline all-rounder* label is the cascade's else-branch and is named to say so.
It used to read *All-courter*, which is a claim about court coverage and net play that
this centroid does not support — its net rate is slightly *below* average — on what is
the largest asserted women's group. Players there are the ones no earlier branch
described, not players who have been found to play all-court tennis.

Labels describe each cluster's *centroid*; a cluster spans a range, so a borderline
player can read as the neighbouring style — Medvedev is a consistent wall who lands among the
big servers because of his serve.

## Honest limitations

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

## What the fingerprint fed, and how that turned out

`reports/player_style_clusters.csv` (player, gender, cluster, archetype, `style_margin`,
`style_confident`, plus the fingerprint features themselves) was the bridge to what was meant
to be the differentiated product: measure each player's shot quality against what their style
predicts, separating skill from style in a way the league-baseline leaderboard in
`chess_point_analysis` cannot.

**That did not work, and the site does not print it.** `class_relative_wpa` benchmarks against
a smooth fit over these features rather than a cluster mean — the right choice, since the
cluster label is a step function that moves — but the ridge penalty is solved to absorb only as
much variance as the four class means did, which it achieves by explaining a shrunken copy of
the whole style axis. The residual keeps the rest: it correlates −0.99 with the raw score and
66% of its variance is rally length. See that experiment's report for the numbers. The
fingerprint is still the right object; what it could not support was a per-player skill verdict
at this resolution.

The one thing the clusters do feed into the site is the archetype line itself, and only where
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
