# Tennis match charting — analysis and a live bracket site

> **[→ Visit Love All](https://anthonyburre.github.io/love-all/)** — explore live Grand Slam, 1000 & 500 draws

The [Match Charting
Project](https://github.com/JeffSackmann/tennis_MatchChartingProject) is a
crowdsourced dataset of **shot-by-shot** records for 5,000+ professional tennis
matches — every rally typed out as point strings. This repo decodes that
notation into queryable tables, derives point/rally/stroke analytics from it,
and publishes an interactive site to GitHub Pages.

## The site — Love All

`docs/` is a GitHub Pages site showing **Grand Slam, Masters/WTA-1000 and ATP/WTA-500
brackets** from ESPN's public feed, drawn as a linked tree with each winner wired to the
next-round match it feeds. ESPN exposes no draw slots, so that linkage is inferred
from names as the draw resolves. The page themes and titles itself to whichever
tournament you're looking at.

The feed carries no tour level — `major` flags the four slams and nothing else, so a 500
and a 125 arrive looking identical. The 1000s are recognized by name, and the 500s are a
hand-kept roster of ESPN tournament ids in `live/levels.py`: ids are the only stable
handle, since sponsor names churn (Queen's arrives as "HSBC Championships") and cities
collide (a WTA 125 plays Rome too). An event that changes level is a one-line edit there.

Live draws show while play is on. Once an event finishes, its draw is frozen into an
archive (`data/history.json`) so it stays in the dropdown to look back on — the site
keeps the last two years of slams, plus the two most recent finished events of every
other tier. On a live or upcoming
match, each box is shaded by how charted its pairing is, taken as the min of the two
players. On a finished draw the shading turns per-match — charted or not — and the
drawer links straight to that match's full chart on Tennis Abstract, or invites you to
be the one who charts it. Click any match and a drawer opens with, for each player: a
style archetype, serve and return rates against the tour average, court patterns (their
stable answers to a given incoming ball, drawn on a court), shot-making triggers, shot
quality relative to that archetype, and an **experimental pre-match win probability**.
All of it is queried in the browser with **DuckDB-WASM** — there is no backend.

Two workflows keep it current, and nothing they generate is committed:

- **`.github/workflows/insights.yml`** (weekly, or manual) rebuilds the compact
  `insights.duckdb` — one row per charted player, plus the recent charted-match index
  the site flags finished matches against — and publishes it as a Release asset.
- **`.github/workflows/live.yml`** (hourly) fetches the current draws, folds any
  newly-finished event into the draw-history asset, reuses the insights DB, and deploys
  `docs/` to Pages.

To run it locally: `match-charting-project site build-insights`, then `... site
build-brackets`, then serve `docs/`. To seed a past event that finished before the site
was watching it, `... history harvest --event Wimbledon --year 2025` (future events are
captured automatically as they finish). The win-prob model, ESPN adapter, history
archive, and insights builder live under `src/match_charting_project/{winprob_match,live,site}`.

## Reading the patterns and court diagrams

Open a matchup and each player's card leads with **court patterns**, written in plain
English: `drive into the BH corner → crosscourt BH slice (1.6× the tour)`. Below them,
**shot-making triggers** are written in shot tokens: `serve wide · BH slice→3`. Click the
**ball path** toggle under either to see it drawn on a small court. The drawer also carries
a short "How to read the shot notation" key of its own.

### Court patterns

A pattern is the player's answer to one incoming ball: the state (the ball's character and
the zone it lands in) and the response (wing, shot type, and line). The multiplier compares
how often the player picks that response to how often the tour picks it **from the same
spot** — so `1.6×` on a crosscourt slice means a genuine preference, not just that slices
happen. The payoff (`wins 52% ▲5 vs tour`) is a separate claim: how often the point ends
up theirs after that response, next to the tour's rate playing the same ball — the
multiplier is the choice, the payoff is what it earns. Two families appear: rally
patterns, and **off the return** — what the server does with their first ball after the
serve, split by the charted depth of the return (short / mid / deep).

Zones in a pattern are named by the **player's own hands**: "the BH corner" is that
player's backhand corner whether they are left- or right-handed. Run-around shots get
their tennis names — a forehand played from the backhand corner is `inside-out` on the
diagonal, `inside-in` down the line. Every pattern shown repeated in both halves of the
player's charted matches; one-off quirks are filtered out.

### The trigger tokens

Each stroke is one token:

- **Wing and type.** `FH` / `BH` is the forehand or backhand wing the player actually hit
  with. The type is `drive` (flat or topspin), `slice` (slice or chip), `net` (volley,
  overhead, or half-volley), or `shot` when the type was not charted. These group a finer
  set in the raw notation, which also records drop shots, lobs, overheads, and so on.
- **Direction.** `→1` / `→2` / `→3` is the third of the court the ball was sent to, as
  fixed thirds named by the right-hander convention. `→·` means the direction was not
  charted.
- **Serves.** A serve is written as its target: `serve wide`, `serve body`, or `serve T`.

A trigger reads as a lead-up — the player's shot, then the opponent's reply — and asks what
that cue provokes. The framework groups winners and unforced errors as one behavioral unit,
the **attempt**: both mean the player went for a finishing shot, and only the execution
differed. "Goes for it" is the attempt rate the cue provokes; "converts" is winners per
attempt; a cue that raises attempts but sinks conversion is a trap — they take the bait.

### The court diagram

The diagram is a **placement map**, not a flight path: it marks where each ball landed and
joins the points in order, faint first and bold last. It comes in two flavors:

- **A pattern** draws the incoming ball landing on the near half — the player's side, so
  "into the BH corner" points where you'd expect — and the response, bold, landing up top.
  For return patterns the incoming bounce sits short, mid-court, or deep to match the
  charted return depth.
- **A trigger sequence** plays out from the near baseline, bounces alternating ends, with
  the small dot anchoring the first stroke (the server's contact when it starts with a
  serve). The notation does not record deuce or ad court, so serves assume the deuce court.

### Zones and how fine the charting really is

The placement is **coarse on purpose**, and the diagram shows only what was charted:

- **Three lateral zones.** Direction is recorded as one of three thirds, not a continuous
  spot, so two shots into different parts of the same third are the same zone. Within a
  third the diagram cannot separate, say, a sharp crosscourt from a safer one.
- **Lines come from zone pairs.** A single zone code never says crosscourt or down the
  line, but a pattern knows both ends — the zone the ball arrived in fixes where the player
  stood, so zone-to-zone geometry names the line. The two ends face each other, which is why
  a reply into the *same-numbered* third travels the diagonal.
- **Depth is thin.** The raw notation carries a coarse depth (shallow / mid / deep) on
  about three-quarters of returns but few later balls, so only the off-the-return patterns
  use it. Trigger drawings put every rally bounce at one mid-court depth.
- **Three serve targets.** Wide, body, or T, placed in the service box the serve crosses
  into.

### Does handedness matter?

The **wing** is always right: `FH` / `BH` is the stroke the player actually made, taken
straight from the notation, so it holds for left-handers and right-handers alike.

For **court patterns**, handedness is already folded in: the zones are flipped for
left-handers before anything is counted or compared, so "drive into the BH corner" means
the same tennis problem for Nadal as for Federer, and the comparison against the tour is
apples to apples. (This matters — without the flip, a lefty answering his forehand corner
with a forehand posts a huge, meaningless lift against a mostly right-handed tour.)

The **trigger tokens** keep the raw convention: `→1` / `→2` / `→3` are fixed thirds named
by a right-hander's wings (`1` = a righty's forehand corner). The ball is drawn where it
physically went, so the diagram itself never needs adjusting — just remember that for a
left-hander, `→3` is their forehand side.

## Stack

| Layer         | Tool             | Why                                            |
|---------------|------------------|------------------------------------------------|
| ETL           | pandas           | Industry-standard tabular wrangling            |
| Storage       | Apache Parquet   | Columnar, typed, portable                      |
| Query/serving | DuckDB           | Fast in-process SQL; runs in-browser via WASM  |
| Viz           | matplotlib       | Static figures; Plotly/JS for the web frontend |
| Packaging     | uv + hatchling   | Reproducible, modern Python tooling            |

## Quickstart

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

## Repository layout

A place for each kind of work, so the library doesn't turn into a junk drawer:

```
src/match_charting_project/        # the reusable, importable library
├── ingest/            # download, normalize, validate, build, provenance
├── analysis/          # tiers, coverage aggregations, career-era splitting (player_eras)
├── shots/             # notation decoder (+ points_parsed) + point win-prob eval / shot WPA
└── viz/               # figure renderers
tests/                 # pytest suite (e.g. notation decoder vs charted stats)
data/                  # raw/ + processed/ parquet + tennis.duckdb   (gitignored)
notebooks/             # numbered, disposable exploration
experiments/           # one-off idea spikes that aren't library-worthy yet
reports/               # generated outputs (data_quality.md, figures/, summaries)
docs/                  # the live Love All site (Pages)
```

**Where does new work go?** Reusable logic → a module under `src/match_charting_project/`.
A throwaway exploration → `notebooks/`. A self-contained idea you're not sure
about → `experiments/`. Generated artifacts → `reports/` (never committed by
hand; regenerated by the CLI).

## Data model (after ingestion)

- **`matches`** — one row per match. Normalized columns plus derived ones:
  `gender`, `year`, `tier` (Grand Slam / Masters-1000 / etc.), and quality flags
  (`surface_valid`, `surface_clean`, `is_qualifying`, `date_valid`).
- **`points`** — one row per point. Raw shot notation in `first_serve` /
  `second_serve` (e.g. `4b37y1r3n#`) — the basis for derived shot analytics.
- **`points_parsed`** — one row per point, decoded from the notation (`rally_len`,
  `outcome`, ending wing/kind, `server_won`); built by `match-charting-project shots`.
- **`player_eras`** *(optional; built by `match-charting-project eras`)* — one row per
  player-era. A long career is split into early/late entities **only** when its style
  genuinely changed (`evolved` flag), so analyses can treat e.g. early- vs late-career
  Agassi as distinct players; join points on `year BETWEEN year_start AND year_end`.
  Methodology & justification live in `experiments/career_splits/`.
- **`stats_overview`** (+ more with `--what all`) — the project's own
  pre-aggregated stat lines; a **validation reference** for metrics we compute.
- **`source_manifest`** — per-file upstream last-commit date + local size
  (freshness / provenance).
- **`ingestion_runs`** — append-only log of each local ingest (cadence over time).

### Tournament tiering

The raw data has no tier field, so `analysis/tiers.py` derives one from the
free-text tournament name (Grand Slam / Masters-WTA 1000 / Tour Finals / Tour
250-500 / Team event / Other). ~99.8% of matches classify. Note: 250 vs 500 is
deliberately **not** split — even Sackmann's authoritative ATP data collapses
them into one level. Splitting them (and validating the whole mapping) by
cross-referencing the `tennis_atp` / `tennis_wta` repos is a documented next step.

The live site does need the split, to know which events to serve, so it keeps its own
roster of 500s by ESPN tournament id (`live/levels.py`). That roster covers the current
calendar only and is deliberately kept out of `tiers.py`, so the tier column over 65
years of charted matches stays as honest — and as stable — as the source data allows.

### Coverage methodology

"Coverage" means **charted ÷ played**, not a raw charted count — so it needs a
denominator. We use the ones that are known exactly without external results
data, and keep men and women in separate figures throughout (every figure is
rendered as a `*_men.png` / `*_women.png` pair):

- **Grand Slams** — a singles main draw is always 128 players = **127 matches**, so coverage is `charted / 127` per slam-year-gender.
  Valid for all four slams since 1990.
- **Masters 1000 / WTA 1000** — draws vary (56 / 96 / 128), so there is no fixed
  full-draw denominator. The late rounds are invariant, though: every draw has
  R16=8, QF=4, SF=2, F=1 = **15 matches**. We report `charted / 15` from the
  round of 16 onward.

Two findings fall straight out: nothing is fully charted (best slam draw ≈ 50%),
and charting skews hard to the later rounds (slam finals ~80–90% vs. R128 ~5%).
Extending true coverage to the 250/500 tiers needs real played-match counts from
the `tennis_atp` / `tennis_wta` repos — a documented next step.

## Attribution & license

The underlying data is © the Match Charting Project contributors, licensed
**CC BY-NC-SA 4.0** (attribution required, **non-commercial** use only). This
repository's *code* is MIT-licensed; the *data* it downloads remains under the
Match Charting Project license. Please credit the Match Charting Project in any
derived work.

- Data: https://github.com/JeffSackmann/tennis_MatchChartingProject
- License: https://creativecommons.org/licenses/by-nc-sa/4.0/
