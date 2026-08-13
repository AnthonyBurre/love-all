# Class-relative shot quality

*Decision quality (avg win-prob conceded per stroke, lower = better) measured with one style-blind eval, then compared against what a player's own style predicts. `class_rel_z` < 0 means a player concedes less than their style predicts. Read the validation section first — the raw metric is mostly style, and only the class-relative residual carries any skill claim at all. CSV has every player; below are the highlights.*

## Is `avg_wpa_lost` measuring shot quality?

Mostly not. WPA telescopes inside a point, so the total swing is near-fixed and the per-stroke average is identically *(win probability conceded per point) / (strokes per point)* — the second factor does most of the work.

| | players | reliability | r with rally length | style CV R² | reliable non-style |
|---|---|---|---|---|---|
| Men | 241 | 0.94 | -0.87 | 0.91 | **0.03** |
| Women | 152 | 0.93 | -0.83 | 0.82 | **0.11** |

Reliability is split-half by match hash, Spearman-Brown corrected. Style R² is out-of-fold over the 12 fingerprint features, so it is variance style genuinely predicts rather than variance it can be fitted to. The last column is reliability minus that: the most of the metric's spread that could be skill rather than style or noise.

The residual — the part `class_rel_z` reports — is the only place a skill claim can live, and it is much weaker than the raw metric:

| | `class_rel_z` reliability | against a full style fit |
|---|---|---|
| Men | +0.91 | +0.43 |
| Women | +0.88 | +0.60 |

The two columns differ because λ is solved to absorb only as much variance as the four class means did (see `style_benchmark`), which is a third to a half of the total — so a good deal of style is still sitting inside the published residual and lending it stability that is not skill. The right column removes every bit of style the fingerprint can reach, and is the honest ceiling. Either way it is a verdict's worth of signal, not a score's, which is what the site prints it as.

What the raw metric ranks, most to least (accuracy score, with the average rally length of the points they played):

| Men: top | acc | rally | bottom | acc | rally |
|---|---|---|---|---|---|
| Mats Wilander | 72.8 | 6.7 | Christopher Eubanks | 52.6 | 3.5 |
| Gilles Simon | 70.7 | 6.3 | Ivo Karlovic | 53.8 | 3.1 |
| Bjorn Borg | 70.7 | 5.9 | Reilly Opelka | 54.8 | 3.5 |
| Fabrice Santoro | 70.6 | 5.9 | Goran Ivanisevic (1995–2001) | 55.1 | 3.0 |

| Women: top | acc | rally | bottom | acc | rally |
|---|---|---|---|---|---|
| Caroline Wozniacki | 73.1 | 5.7 | Alycia Parks | 48.7 | 3.6 |
| Sara Sorribes Tormo | 72.5 | 7.1 | Jelena Ostapenko | 54.5 | 3.7 |
| Sara Errani | 71.2 | 5.9 | Dayana Yastremska | 55.4 | 4.4 |
| Agnieszka Radwanska | 71.1 | 5.5 | Sabine Lisicki | 56.1 | 4.0 |

That is a grinder-to-servebot ordering. It is why the site stopped printing the 0–100 score as a figure and prints rally length plus the three-band class-relative verdict instead.

## Men

**Best relative to their style** (most below their archetype's mean):

| player | archetype | avg_wpa_lost | z | overall rank |
|---|---|---|---|---|
| Mats Wilander | Baseline grinder / counterpuncher | 0.053 | -2.32 | 1 |
| Fabrice Santoro | Slice & variety | 0.058 | -2.07 | 4 |
| Bjorn Borg | Baseline grinder / counterpuncher | 0.058 | -1.94 | 3 |
| Tomas Martin Etcheverry | Baseline grinder / counterpuncher | 0.059 | -1.89 | 5 |
| Gilles Simon | Baseline grinder / counterpuncher | 0.058 | -1.87 | 2 |
| Lleyton Hewitt (1998–2004) | Baseline grinder / counterpuncher | 0.060 | -1.85 | 10 |
| Roberto Bautista Agut | Baseline grinder / counterpuncher | 0.059 | -1.82 | 6 |
| Roberto Carballes Baena | Baseline grinder / counterpuncher | 0.059 | -1.75 | 7 |
| Daniil Medvedev | Big-serving baseliner | 0.062 | -1.74 | 15 |
| Novak Djokovic (2017–2026) | Baseline grinder / counterpuncher | 0.061 | -1.72 | 13 |
| Thomas Muster | Baseline grinder / counterpuncher | 0.060 | -1.69 | 9 |
| Andrei Chesnokov | Baseline grinder / counterpuncher | 0.059 | -1.62 | 8 |

**Best in each archetype:**

- *Baseline grinder / counterpuncher* (105 players): **Mats Wilander** (0.053)
- *Big-serving baseliner* (80 players): **Daniil Medvedev** (0.062)
- *Net-rusher / serve-volleyer* (31 players): **Pete Sampras (1990–1995)** (0.077)
- *Slice & variety* (26 players): **Fabrice Santoro** (0.058)

## Women

**Best relative to their style** (most below their archetype's mean):

| player | archetype | avg_wpa_lost | z | overall rank |
|---|---|---|---|---|
| Caroline Wozniacki | Baseline grinder / counterpuncher | 0.052 | -2.60 | 1 |
| Agnieszka Radwanska | Baseline grinder / counterpuncher | 0.057 | -1.94 | 4 |
| Linda Fruhvirtova | All-courter | 0.060 | -1.87 | 6 |
| Sara Sorribes Tormo | Baseline grinder / counterpuncher | 0.054 | -1.73 | 2 |
| Daria Kasatkina (2015–2022) | Baseline grinder / counterpuncher | 0.060 | -1.71 | 7 |
| Sara Errani | Baseline grinder / counterpuncher | 0.057 | -1.67 | 3 |
| Angelique Kerber | Baseline grinder / counterpuncher | 0.061 | -1.63 | 11 |
| Martina Hingis | Baseline grinder / counterpuncher | 0.059 | -1.62 | 5 |
| Magdalena Frech | Baseline grinder / counterpuncher | 0.061 | -1.59 | 10 |
| Daria Kasatkina (2023–2026) | All-courter | 0.064 | -1.50 | 12 |
| Katie Volynets | Baseline grinder / counterpuncher | 0.061 | -1.49 | 8 |
| Flavia Pennetta | Baseline grinder / counterpuncher | 0.064 | -1.45 | 13 |

**Best in each archetype:**

- *All-courter* (60 players): **Linda Fruhvirtova** (0.060)
- *Baseline grinder / counterpuncher* (49 players): **Caroline Wozniacki** (0.052)
- *Big serve / first-strike* (39 players): **Jennifer Brady** (0.070)
- *Slice & net specialist* (4 players): **Tatjana Maria** (0.068)
