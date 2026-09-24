# Love All

> **[→ Visit Live Site](https://anthonyburre.github.io/love-all/)** to explore live Grand Slam, ATP, and WTA draws

The [Match Charting Project](https://github.com/JeffSackmann/tennis_MatchChartingProject) is a
crowdsourced dataset of **shot-by-shot** records for 11,600+ professional tennis
matches typed out as point strings. This repo decodes that notation into queryable tables
(1.85M points), derives point/rally/stroke analytics from it, and publishes an interactive
site to GitHub Pages.


## The experiments

Every folder under `experiments/` has a `README.md` stating its question, the code that
answers it, and what it found. They write their full output to `reports/`.

Some build on a point-level win-probability eval and per-shot WPA (win
probability added), which began as a
port of chess engine analysis to tennis points. See
[`chess_point_analysis`](experiments/chess_point_analysis/).

### Player / Rally Analysis

| experiment | the question | what it found |
| --- | --- | --- |
| [`shot_language`](experiments/shot_language/) | How predictable is a player's shot sequence? | Most varied: Rusedski, Moutet, Santoro, Rafter; Navratilova, Maria, Niculescu. Most predictable: Basilashvili, Cilic; Samsonova, Giorgi, Ostapenko. Junkballers and serve-volleyers score high, flat first-strike baseliners low. Zones are mirrored for left-handers, without which handedness alone explained over half the spread. |
| [`shot_patterns`](experiments/shot_patterns/) | Which lead-ups precede a player's winners, and which precede their errors? | Distinctive, and they match expectations. Sampras finishes at the net. Federer puts away the forehand-corner-to-weak-backhand, and his *trouble* is backhand-to-backhand, his well-known pressure point. |
| [`shot_triggers`](experiments/shot_triggers/) | Are a player's winners and errors really two separate books? | No, they share one decision: the **aggressive shot**. That yields cues that raise **aggressive shot frequency**, their conversion rates, and **traps**: cues that raise the frequency but convert worse than the player's other cues. Every figure is held out. Ships to the site. |
| [`court_response`](experiments/court_response/) | What does a player do with a given incoming ball? | Enough stability to read as a scouting report: split-half r = 0.73 (men) / 0.69 (women) over ~43k state-response cells. Federer's crosscourt backhand slice, Djokovic's backhand down the line. The field is weighted to each player's own era, without which a pre-2000 slicer's lift is mostly the decade. Every figure is **held out**, and about half of a discovered edge survives that. Known limit: 16.4% of cells answer the same ball differently in the opening than mid-rally. |
| [`serve_plus_one`](experiments/serve_plus_one/) | The server's third ball, with the service court in the state. | Pooling the courts was averaging two different shots. Nadal answers the same mid-depth return with a crosscourt forehand on the deuce side and an inside-out forehand on the ad side, one of 597 such disagreements across 260 players. 725 patterns over 414 players survive the FDR correction. Ships to the site. |
| [`context_length`](experiments/context_length/) | How many shots of history does charted data actually support? | **Two. The third actively hurts** held-out log-loss. And a player's top-5 signature list overlaps only J≈0.22 between halves of their own data, so much of any specific list is sampling luck. |
| [`rally_patterns`](experiments/rally_patterns/) | Blind out the serve, return and both +1 shots. What patterns are left in the rally alone? | **Almost nothing deeper than two shots.** Of 1,752 serve-blind 3-shot candidates, 2 survive; of 362 at four shots, none. Two-shot rally patterns are real: 89 survive, 89% replicate, and one found at lift L posts about 1 + 0.5(L−1) out of sample. Letting the context reach back into the opening returns seven times as many patterns, but they keep only a third of their discovered edge against two thirds for the rally-only pair. Blinding also makes serving/returning and deuce/ad poolable, which is tested directly (2 of 1,441 cells reject). The site ships no 3–4 shot tier. |
| [`serve_tendencies`](experiments/serve_tendencies/) | Which serve-placement stats can a player card safely carry? | Where a player serves is a measurement (split-half r = 0.58, ~860 serves for 80% signal); **what the placement earns is not** (r = 0.22, ~11,000 serves). Placement is re-decided per match, so the binomial sample-size rule is optimistic ~4x. |
| [`player_styles`](experiments/player_styles/) | What style archetypes are there? | Four per tour, matching how fans talk: net-rusher (Sampras, McEnroe), baseline grinder (Djokovic, Nadal), slice & variety (Wawrinka, Federer), big-serving baseliner (Medvedev, Zverev). Style is a continuum, so about a third of entities sit too near a boundary to name and are reported as "between styles" rather than assigned. |
| [`career_splits`](experiments/career_splits/) | Should a long career split into eras, or is that just two noisier samples of one player? | Split **selectively**. Most careers are stable; 34 changed clearly, and they match known changes (Sabalenka's serve yips, Clijsters' comeback). Justifies `player_eras`, 358 → 392 entities. |
| [`blind_reid`](experiments/blind_reid/) | Hide every name. Can you tell who is across the net purely from the shots coming back? | Yes, and **the serve is the weakest way to do it**. Response strokes alone reach AUC 0.685 on held-out players against the serve block's 0.643. Identity also fades measurably across years. |
| [`class_relative_wpa`](experiments/class_relative_wpa/) | Who beats the average for *their own style*, rather than the field's? | **Not at this resolution.** `class_rel_z` was meant to judge a shotmaker against other shotmakers, but the residual correlates −0.99 with the raw score it is taken from and 66% of its variance is rally length: the ridge λ is solved to match the class means' R², which it buys by leaving a scaled copy of the style axis in the residual. It said no male serve-volleyer had ever been ahead of similar players. Does not ship. |

### Win probability

None of these ship to the site. See [The site](#the-site) for why.

| experiment | the question | what it found |
| --- | --- | --- |
| [`match_winprob`](experiments/match_winprob/) | P(win the match) from the score, and what each point is worth. | Federer's 2019 final peaks at **98.8%** serving at 8-7, 40-15, two championship points, then collapses. It stays under 99% because the model credits Djokovic's elite return. |
| [`score_aware_eval`](experiments/score_aware_eval/) | Does telling the point eval *where in the match* a point sits improve it? | **No.** Points are nearly independent given the rally state, the classic Klaassen–Magnus result. This negative is what justified handling the score with an analytic tree instead. |
| [`class_aware_eval`](experiments/class_aware_eval/) | Does telling the eval *who* is playing improve it? | **No.** Style-blind wins on held-out data at both granularities, which is what stopped class-relative WPA from being built on a more complicated eval. |
| [`surface_winprob`](experiments/surface_winprob/) | Does surface improve match prediction? | **No.** Players do differ by surface, but both players shift together and only the *relative* tilt moves a prediction. Too small and too thinly sampled to pay. |
| [`form_streakiness`](experiments/form_streakiness/) | Does recent form help, and are some players streaky? | **No** to both. The form signal is real (~8σ) but tiny in absolute terms, and per-player streakiness is mostly noise at this resolution. |

## The site

`docs/` is a GitHub Pages site showing **Grand Slam, Masters/WTA-1000, ATP/WTA-500 and ATP-250
brackets**. Open any matchup to see average point length, shot variety, shot mix, serve
direction, court patterns, shot-making triggers, and more! All of it is queried in the browser
with **DuckDB-WASM**, with no backend. [`docs/README.md`](docs/README.md) explains how to read
the patterns, trigger tokens and court diagrams.

The panel deliberately does not predict match outcomes, since that is not the strength of this
dataset and every other tennis site already does so. When the match itself is charted it shows
a win-probability curve over every point, plus match summary stats for each player. The curve
starts from strengths estimated only from **older** matches (`walk_forward_strength` in
`winprob_match.py`).

| feed | source | what it gives | refresh |
| --- | --- | --- | --- |
| scores | ESPN scoreboard | matches, rounds, live scores | hourly while a draw is on, daily between |
| calendar | Wikipedia season pages | which events exist, tour level, surface | daily |
| draws | Wikipedia per-event draw pages | round-1 slot order, seeds, byes | once per event |
| insights | Match Charting Project | per-player charted history | weekly |

ESPN is the only free source for scores, and it carries **no tour level and no draw
structure**, so everything structural comes from Wikipedia. A Wikipedia draw sheet is used only
once it agrees with ESPN about who plays whom (`live/feeds.py`). Both Wikipedia feeds are cached
under `data/` (gitignored, carried by CI as Release assets), so **no draw sheet is committed to
the repo**. Requests identify themselves as `love-all/0.1` and link back to this repo.

Once an event finishes, its draw is frozen into an archive so it stays in the dropdown; the
archive keeps the last two years of slams plus the two most recent finished events of every
other tier.

## Quickstart

pandas for ETL, Parquet on disk, DuckDB for query and serving (the same engine runs
in-browser via WASM), matplotlib for static figures, uv + hatchling for packaging.

```bash
uv sync --extra analysis     # venv + deps (incl. matplotlib/jupyter)
uv run match-charting-project ingest     # download -> parquet + duckdb (+ provenance)
uv run match-charting-project coverage   # render coverage figures + summary
uv run match-charting-project info       # list tables and row counts
```

### CLI

| Command                       | What it does                                              |
|-------------------------------|----------------------------------------------------------|
| `ingest [--what core\|all]`   | download + capture upstream freshness + build everything |
| `download [--what core\|all]` | just fetch raw CSVs into `data/raw`                       |
| `build [--stats core\|all]`   | (re)build parquet + duckdb from `data/raw` (offline)     |
| `coverage`                    | render per-gender coverage figures + `reports/coverage_summary.md` |
| `shots`                       | decode the point notation into the `points_parsed` table |
| `eras`                        | build the optional `player_eras` table (split evolving careers) |
| `validate`                    | print the data-quality report                            |
| `info`                        | summarize the duckdb database                            |

`core` = matches + points + Overview stats (~200 MB). `all` adds every
pre-aggregated `-stats-` table (~550 MB).

### Building the site

```bash
match-charting-project feeds calendar        # once; without it the site can't tell a 500 from a 250
match-charting-project site build-insights
match-charting-project site build-match-details   # per-match sidecars; needs tennis.duckdb
match-charting-project site build-brackets        # then serve docs/
```

`... feeds draws` fetches draw sheets by hand if you want to check them; the site build does
it anyway. To seed a past event that finished before the site was watching it,
`... history harvest --event Wimbledon --year 2025`.

Two workflows keep the live site current, and nothing either generates is committed:

- **`.github/workflows/insights.yml`** (weekly) rebuilds `insights.duckdb` and the per-match
  sidecars the drawer reads on a charted match, and publishes both as Release assets. They
  are built here because they need the point notation in `tennis.duckdb`.
- **`.github/workflows/live.yml`** (hourly) fetches scores, picks up new draw sheets, folds
  finished events into the archive, copies in only the sidecars the current draws reference,
  and deploys `docs/` to Pages.

## Repository layout

```
src/match_charting_project/        # the reusable, importable library
├── ingest/            # download, normalize, validate, build, provenance
├── analysis/          # tiers, coverage aggregations, career-era splitting (player_eras)
├── shots/             # notation decoder (+ points_parsed) + point win-prob eval / shot WPA
└── viz/               # figure renderers
tests/                 # pytest suite (e.g. notation decoder vs charted stats)
data/                  # raw/ + processed/ parquet + tennis.duckdb   (gitignored)
experiments/           # self-contained idea spikes; they graduate into src/ if they earn it
reports/               # generated outputs, never committed by hand
docs/                  # the live Love All site (Pages); README.md explains how to read it
```

## Data model (after ingestion)

- **`matches`** — one row per match. Normalized columns plus derived ones:
  `gender`, `year`, `tier`, and quality flags (`surface_valid`, `surface_clean`,
  `is_qualifying`, `date_valid`). The raw data has no tier field, so `analysis/tiers.py`
  derives one from the tournament name; 250s and 500s share one bucket, as in Sackmann's
  ATP data.
- **`points`** — one row per point. Raw shot notation in `first_serve` /
  `second_serve` (e.g. `4b37y1r3n#`), the basis for derived shot analytics.
- **`points_parsed`** — one row per point, decoded from the notation (`rally_len`,
  `outcome`, ending wing/kind, `server_won`); built by `match-charting-project shots`.
- **`player_eras`** *(optional; built by `match-charting-project eras`)* — one row per
  player-era. A long career is split into early/late entities **only** when its style
  changed (`evolved` flag), so analyses can treat e.g. early- vs late-career
  Agassi as distinct players; join points on `year BETWEEN year_start AND year_end`.
  Methodology & justification live in `experiments/career_splits/`.
- **`stats_overview`** (+ more with `--what all`) — the project's own
  pre-aggregated stat lines; a **validation reference** for metrics we compute.
- **`source_manifest`** — per-file upstream last-commit date + local size
  (freshness / provenance).
- **`ingestion_runs`** — append-only log of each local ingest (cadence over time).

Coverage is reported as charted ÷ played, per slam draw and per 1000-level late rounds, in
[`reports/coverage_summary.md`](reports/coverage_summary.md). Nothing is fully charted (the
best slam draw is about 50%), and charting skews hard to the later rounds. The denominators
and their limits are explained in `analysis/coverage.py`.

## Attribution & license

The underlying data is © the Match Charting Project contributors, licensed
**CC BY-NC-SA 4.0** (attribution required, **non-commercial** use only). This
repository's *code* is MIT-licensed; the *data* it downloads remains under the
Match Charting Project license. Please credit the Match Charting Project in any
derived work.

- Data: https://github.com/JeffSackmann/tennis_MatchChartingProject
- License: https://creativecommons.org/licenses/by-nc-sa/4.0/
