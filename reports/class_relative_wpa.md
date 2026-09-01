# Class-relative shot quality

*Decision quality (avg win-prob conceded per stroke, lower = better) measured with one style-blind eval, then compared against what a player's own style predicts. `class_rel_z` < 0 means a player concedes less than their style predicts. Read the validation section first — the raw metric is mostly style, and only the class-relative residual carries any skill claim at all. CSV has every player; below are the highlights.*

## Is `avg_wpa_lost` measuring shot quality?

Mostly not. WPA telescopes inside a point, so the total swing is near-fixed and the per-stroke average is identically *(win probability conceded per point) / (strokes per point)* — the second factor does most of the work.

| | players | reliability | r with rally length | style CV R² | reliable non-style |
|---|---|---|---|---|---|
| Men | 241 | 0.94 | -0.86 | 0.91 | **0.03** |
| Women | 152 | 0.93 | -0.83 | 0.82 | **0.11** |

Reliability is split-half by match hash, Spearman-Brown corrected. Style R² is out-of-fold over the 12 fingerprint features, so it is variance style genuinely predicts rather than variance it can be fitted to. The last column is reliability minus that: the most of the metric's spread that could be skill rather than style or noise.

The residual — the part `class_rel_z` reports — is the only place a skill claim can live, and it is much weaker than the raw metric:

| | `class_rel_z` reliability | against a full style fit |
|---|---|---|
| Men | +0.89 | +0.43 |
| Women | +0.87 | +0.61 |

The left column looks strong, and that is the trap: λ is solved to absorb only as much variance as the four class means did (see `style_benchmark`), a third to a half of the total, so plenty of style is still sitting inside the published residual and lending it a stability that is not skill. The right column removes every bit of style the fingerprint can reach and is the honest ceiling on the skill claim: a three-band verdict's worth of signal, not a score's.

What the raw metric ranks, most to least (accuracy score, with the average rally length of the points they played):

| Men: top | acc | rally | bottom | acc | rally |
|---|---|---|---|---|---|
| Mats Wilander | 72.8 | 6.7 | Christopher Eubanks | 52.6 | 3.5 |
| Fabrice Santoro | 70.7 | 5.9 | Ivo Karlovic | 54.1 | 3.1 |
| Gilles Simon | 70.6 | 6.3 | Reilly Opelka | 54.8 | 3.5 |
| Bjorn Borg | 70.6 | 5.9 | Goran Ivanisevic (1995–2001) | 55.7 | 3.0 |

| Women: top | acc | rally | bottom | acc | rally |
|---|---|---|---|---|---|
| Caroline Wozniacki | 73.2 | 5.7 | Alycia Parks | 48.8 | 3.6 |
| Sara Sorribes Tormo | 72.4 | 7.1 | Jelena Ostapenko | 54.6 | 3.7 |
| Agnieszka Radwanska | 71.3 | 5.5 | Dayana Yastremska | 55.0 | 4.4 |
| Sara Errani | 71.1 | 5.9 | Sabine Lisicki | 56.3 | 4.0 |

That is a grinder-to-servebot ordering, which is why neither this score nor the class-relative verdict built on it ships to the site. The panel prints rally length and no quality judgement at all.

## Men

**Best relative to their style** (most below their archetype's mean):

| player | archetype | avg_wpa_lost | z | overall rank |
|---|---|---|---|---|
| Mats Wilander | Baseline grinder / counterpuncher | 0.053 | -2.21 | 1 |
| Fabrice Santoro | Baseline grinder / counterpuncher | 0.058 | -2.13 | 2 |
| Tomas Martin Etcheverry | Baseline grinder / counterpuncher | 0.059 | -1.98 | 5 |
| Lleyton Hewitt (1998–2004) | Baseline grinder / counterpuncher | 0.060 | -1.96 | 10 |
| Bjorn Borg | Baseline grinder / counterpuncher | 0.058 | -1.90 | 4 |
| Roberto Bautista Agut | Baseline grinder / counterpuncher | 0.059 | -1.84 | 7 |
| Daniil Medvedev | Big-serving baseliner | 0.062 | -1.83 | 15 |
| Gilles Simon | Baseline grinder / counterpuncher | 0.058 | -1.81 | 3 |
| Novak Djokovic (2017–2026) | Baseline grinder / counterpuncher | 0.061 | -1.77 | 12 |
| Roberto Carballes Baena | Baseline grinder / counterpuncher | 0.059 | -1.76 | 6 |
| Thomas Muster | Baseline grinder / counterpuncher | 0.060 | -1.68 | 9 |
| Alex Corretja | Baseline grinder / counterpuncher | 0.062 | -1.65 | 14 |

**Best in each archetype:**

- *Baseline grinder / counterpuncher* (83 players): **Mats Wilander** (0.053)
- *Big-serving baseliner* (104 players): **Daniil Medvedev** (0.062)
- *Net-rusher / serve-volleyer* (29 players): **Pete Sampras (1990–1995)** (0.076)
- *Slice & variety* (26 players): **Daniel Evans** (0.068)

## Women

**Best relative to their style** (most below their archetype's mean):

| player | archetype | avg_wpa_lost | z | overall rank |
|---|---|---|---|---|
| Caroline Wozniacki | Baseline grinder / counterpuncher | 0.052 | -2.64 | 1 |
| Agnieszka Radwanska | Baseline grinder / counterpuncher | 0.057 | -1.93 | 3 |
| Linda Fruhvirtova | Baseline all-rounder | 0.060 | -1.91 | 6 |
| Daria Kasatkina (2015–2022) | Baseline grinder / counterpuncher | 0.060 | -1.70 | 7 |
| Martina Hingis | Baseline grinder / counterpuncher | 0.059 | -1.61 | 5 |
| Angelique Kerber | Baseline grinder / counterpuncher | 0.061 | -1.59 | 11 |
| Magdalena Frech | Baseline grinder / counterpuncher | 0.061 | -1.54 | 10 |
| Sara Sorribes Tormo | Baseline grinder / counterpuncher | 0.054 | -1.53 | 2 |
| Sara Errani | Baseline grinder / counterpuncher | 0.057 | -1.52 | 4 |
| Daria Kasatkina (2023–2026) | Baseline all-rounder | 0.064 | -1.52 | 13 |
| Flavia Pennetta | Baseline grinder / counterpuncher | 0.064 | -1.51 | 12 |
| Katie Volynets | Baseline grinder / counterpuncher | 0.061 | -1.43 | 9 |

**Best in each archetype:**

- *Baseline all-rounder* (76 players): **Linda Fruhvirtova** (0.060)
- *Baseline grinder / counterpuncher* (33 players): **Caroline Wozniacki** (0.052)
- *Big serve / first-strike* (36 players): **Lindsay Davenport** (0.074)
- *Slice & net specialist* (7 players): **Amelie Mauresmo** (0.067)
