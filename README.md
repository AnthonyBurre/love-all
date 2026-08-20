# Tennis match charting — analysis and a live bracket site

> **[→ Visit Tournament Analyzer](https://anthonyburre.github.io/love-all/)** — explore live Grand Slam, ATP/WTA 1000 & 500 draws

The [Match Charting Project](https://github.com/JeffSackmann/tennis_MatchChartingProject) is a
crowdsourced dataset of **shot-by-shot** records for 11,600+ professional tennis
matches typed out as point strings. This repo decodes that notation into queryable tables
(1.85M points), derives point/rally/stroke analytics from it, and publishes an interactive
site to GitHub Pages.


## The experiments

Every folder under `experiments/` has a `README.md` stating its question, the code that
answers it, and what it found. They write their output to `reports/`.

### Player / Rally Analysis 

| experiment | the question | what it found |
| --- | --- | --- |
| [`chess_point_analysis`](experiments/chess_point_analysis/) | Can chess-analysis techniques be ported to a tennis point? | Yes. A point string is a move list, so it gets an engine eval, WPA per shot, and an opening explorer. The decoder validates to within 1–5% of the project's own stat lines. |
| [`shot_language`](experiments/shot_language/) | How predictable is a player's shot sequence? | Most varied: Rusedski, Moutet, Santoro, Rafter; Navratilova, Maria, Niculescu. Most predictable: Basilashvili, Cilic; Samsonova, Giorgi, Ostapenko. Junkballers and serve-volleyers score high, flat first-strike baseliners low. Zones are mirrored for left-handers, without which handedness alone explained over half the spread. |
| [`shot_patterns`](experiments/shot_patterns/) | Which lead-ups precede a player's winners, and which precede their errors? | Distinctive and face-valid. Sampras finishes at the net. Federer puts away the forehand-corner-to-weak-backhand, and his *trouble* is backhand-to-backhand, the textbook pressure point. |
| [`shot_triggers`](experiments/shot_triggers/) | Are a player's winners and errors really two separate books? | No, they share one decision: the **aggressive shot**. That yields cues that raise **aggressive shot frequency**, conversion rates, and **traps**, meaning cues that raise the frequency but convert worse than the player's *other* cues do. A cue must clear a per-player FDR correction and hold its sign in both halves of their matches. Ships to the site. |
| [`court_response`](experiments/court_response/) | What does a player do with a given incoming ball? | Enough stability to read as a scouting report: split-half r = 0.73 (men) / 0.69 (women) over ~43k state-response cells. Federer's crosscourt backhand slice, Djokovic's backhand down the line. The field is weighted to each player's own era, without which a pre-2000 slicer's lift is mostly the decade. |
| [`serve_plus_one`](experiments/serve_plus_one/) | The server's third ball, with the service court in the state. | Pooling the courts was averaging two different shots. Nadal answers the same mid-depth return with a crosscourt forehand on the deuce side and a forehand down the line on the ad side. 603 such disagreements across 260 players. 725 patterns over 414 players survive a per-player FDR correction. Each player is profiled at the finest state their charting funds. Ships to the site. |
| [`context_length`](experiments/context_length/) | How many shots of history does charted data actually support? | **Two. The third actively hurts** held-out log-loss. And a player's top-5 signature list overlaps only J≈0.22 between halves of their own data, so much of any specific list is sampling luck. |
| [`deep_patterns`](experiments/deep_patterns/) | For the most heavily charted players, do 3–4 shot patterns survive anyway? | 36 do, across 15 players, through a quadruple gate: beat your own parent pattern, replicate in both halves, clear a binomial test, and survive Benjamini-Hochberg across every context that player was screened on. The correction is what does the work — a heavily charted player is screened on 600+ contexts, so an uncorrected threshold returned roughly twice as many. Shipped as a gold-star tier. |
| [`serve_side`](experiments/serve_side/) | Does deuce vs ad court hide structure? | Yes, and nothing else here conditioned on it. The direction codes mean **opposite wings** on the two sides, so serve analysis that ignores side is averaging two different shots together. |
| [`serve_tendencies`](experiments/serve_tendencies/) | Which serve-placement stats can a player card safely carry? | Where a player serves is a measurement (split-half r = 0.58, ~860 serves for 80% signal); **what the placement earns is not** (r = 0.22, ~11,000 serves). Placement is re-decided per match, so the binomial sample-size rule is optimistic ~4x. |
| [`player_styles`](experiments/player_styles/) | What style archetypes are there? | Four per tour, matching how fans talk: net-rusher (Sampras, McEnroe), baseline grinder (Djokovic, Nadal), slice & variety (Wawrinka, Federer), big-serving baseliner (Medvedev, Zverev). Style is a continuum, so about a third of entities sit too near a boundary to name and are reported as "between styles" rather than assigned. |
| [`career_splits`](experiments/career_splits/) | Should a long career split into eras, or is that just two noisier samples of one player? | Split **selectively**. Most careers are stable; 34 genuinely evolved, and those detections are face-valid (Sabalenka's serve yips, Clijsters' comeback). Justifies `player_eras`, 358 → 392 entities. |
| [`blind_reid`](experiments/blind_reid/) | Hide every name. Can you tell who is across the net purely from the shots coming back? | Yes, and **the serve is the weakest way to do it**. Response strokes alone reach AUC 0.685 on held-out players against the serve block's 0.643. Identity also fades measurably across years. |
| [`class_relative_wpa`](experiments/class_relative_wpa/) | Who beats the average for *their own style*, rather than the field's? | **Not at this resolution.** `class_rel_z` was meant to judge a shotmaker against other shotmakers, but the residual correlates −0.99 with the raw score it is taken from and 66% of its variance is rally length: the ridge λ is solved to match the class means' R², which buys that R² by leaving a scaled copy of the style axis in the residual. It said no male serve-volleyer had ever been ahead of similar players. Pulled from the site; the experiment stands as the negative result. |

### Win probability

These four stand as experiments and none of them ships to the site. The panel used to carry a
pre-match number built on this engine and no longer does — see [The site](#the-site) for why.
The in-match tree remains the right tool for the question it was built for; what it could not
survive was being fed career charted rates and asked to pick a winner.

| experiment | the question | what it found |
| --- | --- | --- |
| [`match_winprob`](experiments/match_winprob/) | P(win the match) from the score, and what each point is worth. | Federer's 2019 final peaks at **98.8%** serving at 8-7, 40-15, two championship points, then collapses. It stays under 99% because the model credits Djokovic's elite return. |
| [`score_aware_eval`](experiments/score_aware_eval/) | Does telling the point eval *where in the match* a point sits improve it? | **No.** Points are nearly independent given the rally state, the classic Klaassen–Magnus result. This negative is what justified handling the score with an analytic tree instead. |
| [`class_aware_eval`](experiments/class_aware_eval/) | Does telling the eval *who* is playing improve it? | **No.** Style-blind wins on held-out data at both granularities, which is what stopped class-relative WPA from being built on a more complicated eval. |
| [`surface_winprob`](experiments/surface_winprob/) | Does surface improve match prediction? | **No.** Players do differ by surface, but both players shift together and only the *relative* tilt moves a prediction. Too small and too thinly sampled to pay. |
| [`form_streakiness`](experiments/form_streakiness/) | Does recent form help, and are some players genuinely streaky? | **No** to both. The form signal is real (~8σ) but tiny in absolute terms, and per-player streakiness is mostly noise at this resolution. |

## The site

`docs/` is a GitHub Pages site showing **Grand Slam, Masters/WTA-1000 and ATP/WTA-500
brackets**, drawn as a linked tree with each winner wired to the next-round match it feeds.
The page themes and titles itself to whichever tournament you're looking at.

| feed | source | what it gives | refresh |
| --- | --- | --- | --- |
| scores | ESPN scoreboard | matches, rounds, live scores | hourly while a draw is on, daily between |
| calendar | Wikipedia season pages | which events exist, tour level, surface | once a season |
| draws | Wikipedia per-event draw pages | round-1 slot order, seeds, byes | once per event |
| insights | Match Charting Project | per-player charted history | weekly |

ESPN is the only free source for scores, and it carries **no tour level and no draw
structure**, so everything structural comes from Wikipedia. Both Wikipedia feeds are cached
under `data/` (gitignored, carried by CI as Release assets), so **no draw sheet is committed
to the repo**, and the hourly build normally makes zero Wikipedia requests.

ESPN is polled only while a draw is being played. Between events the cached scoreboard is
served as-is and the build probes once a day, which is enough to notice the next event
starting. Requests identify themselves as `love-all/0.1` and link back to this repo.

Live draws show while play is on. Once an event finishes its draw is frozen into an archive
so it stays in the dropdown, keeping the last two years of slams plus the two most recent
finished events of every other tier. On a live match each box is shaded by how charted its
pairing is; on a finished draw the shading turns per-match, and the drawer links straight to
that match's full chart on Tennis Abstract or invites you to be the one who charts it. Click
any match and a drawer opens with, for each player: a style archetype, serve and return
rates against the tour average, average point length, shot variety, serve direction, court
patterns, and shot-making triggers. All of it is queried in the browser with
**DuckDB-WASM**, with no backend.

The panel deliberately does **not** predict the match. A pre-match win probability shipped
here for a while, from the analytic score tree in `winprob_match.py` driven by each player's
charted serve and return rates, and it is gone: the tree is exact but its inputs are career
rates over a volunteer-selected sample with no opponent adjustment, and a plain Elo built on
the same charted results beat it on both tours. Predicting the winner is the one thing this
data is worst at and the thing every other tennis site already does. What the charting is
uniquely good for is what a player *does* — which is what the panel is now entirely about.

<details>
<summary><b>Why neither Wikipedia feed is trusted blindly</b> — draw validation and calendar joining</summary>

- **A draw sheet is adopted only once it agrees with the live feed about who plays whom**
  (`wiki.feed_agreement`). This matters more than it sounds: a draw for the wrong event, the
  wrong gender, or last year's edition all parse into perfectly well-formed slots, and
  comparing the *set of players* doesn't separate them either, because tour fields overlap so
  heavily that a slam's draw contains ~84% of a 500's entrants. Pairings do: two players
  share a slot in exactly one draw, so the right sheet scores 1.0 and the nearest wrong
  answers score ≤0.06. A rejected sheet falls back to name inference, degraded but not wrong.
- **The calendar joins to ESPN on venue city *and* week.** City alone is too loose: the WTA
  125 played in Rome matches the Rome 1000 exactly, and the calendar doesn't cover 125s, so
  city-only matching would put a 125 on the site as a 1000. Different week, different
  tournament.

ESPN's own structural gap is worth spelling out: `major` flags the four slams and nothing
else, so a 500 and a 125 arrive looking identical, and there are no draw slots, seeds, or
bracket endpoints anywhere in its API. The Wikipedia season pages state each event's level
and surface, and the per-event draw pages hold real draw sheets as positional
`{{TeamBracket}}` templates, giving slot order, seeds with entry tags, and byes.

The footer names Wikipedia as the source, so a reader who spots an error can fix it there.

</details>

<details>
<summary><b>Running the site locally</b>, and the two workflows that keep it current</summary>

Nothing either workflow generates is committed:

- **`.github/workflows/insights.yml`** (weekly, or manual) rebuilds the compact
  `insights.duckdb`, one row per charted player plus the recent charted-match index the site
  flags finished matches against, and publishes it as a Release asset.
- **`.github/workflows/live.yml`** (hourly) fetches current scores while a draw is on, picks up any
  newly-published draw sheet, refreshes the tour calendar when the season turns, folds any
  newly-finished event into the draw-history asset, reuses the insights DB, and deploys
  `docs/` to Pages. The calendar and draw caches persist as a `feeds-cache` Release asset.

```bash
match-charting-project feeds calendar        # once; without it the site can't tell a 500 from a 250
match-charting-project site build-insights
match-charting-project site build-brackets   # then serve docs/
```

`... feeds draws` fetches draw sheets by hand if you want to check them; the site build does
it anyway. To seed a past event that finished before the site was watching it,
`... history harvest --event Wimbledon --year 2025`. Future events are captured automatically
as they finish. The win-prob model, ESPN adapter, history archive and insights builder live
under `src/match_charting_project/{winprob_match,live,site}`.

</details>

## Reading the site's patterns and diagrams

Everything in the drawer sits under one heading, **charted history**, because that is what
all of it is: these players as the Match Charting Project has them, not as this match went.
Charting is volunteer work, so which matches exist depends on what someone chose to chart,
and that weights the numbers toward big occasions rather than sampling a career evenly. The
drawer says so in a line under the heading, and it is worth keeping in mind for every number
below.

It opens on **charted history**: how much of each player the charting actually has, as a total
and as a bar per season. The total alone cannot tell a breakout year from a decade of steady
work — "195 matches, 2014–2026" reads the same either way — and the difference matters, because
those counts are the denominator of every number below. The bars are charted points, both
players on one axis and one height scale, so a season lines up with the same season across the
gap and the two shapes are directly comparable. Hover or press a bar for that season's exact
counts.

Under it, a **profile band**: what kind of player each of them is, which hand they hold the
racket in, and how long their average point runs. All of it is read through by everything
below — the court drawings further down name their zones by the player's own hand, so a lefty's
forehand corner is a righty's backhand corner. Style is a continuum, so a third of players sit
too near a boundary to name and the band says "between styles" rather than picking one.

The band carries no verdict on how well anyone plays, and it used to carry two. The first was a
0–100 rating: the chess accuracy score ported over, average win probability conceded per stroke
mapped onto a hundred. Win probability telescopes inside a point, so the average conceded *per
stroke* is identically the concession per point divided by the strokes per point, and the second
factor runs the figure — it correlates −0.87 with rally length, the style fingerprint predicts
91% of it out-of-fold, and against a 0.94 split-half reliability that leaves about 3% of its
spread as reliable signal that isn't style. It ranked Santoro and Wilander above Laver and
Karlovic, which is a rally-length table wearing a quality label.

What replaced it was a three-band verdict on the style-corrected residual, and that has gone
too, by the same test. The residual correlates −0.99 with the score it is taken from and 66% of
its variance is still rally length, because the ridge λ is solved to absorb exactly as much
variance as the four class means did — which it buys by explaining a shrunken copy of the whole
style axis and leaving the rest of it in the "residual". It reported that no male serve-volleyer
has ever been ahead of similar players, against half of all grinders. So the panel now prints
the rally length and no judgement at all: **shots per point**, the strokes in an average point,
both players and the serve included, averaged over every charted point that player appeared in.
It is as much a fact about the tennis they get drawn into as about them, which the panel's own
key says.

Then **serve direction**: where their first serve goes on each court side,
laid out the way the server sees the two boxes. Only wide and T are shown, so
the two do not add to 100 — the remainder is the body serve, which `serve_tendencies`
found to be partly a charter's opinion rather than a player's choice. The numbers cover
recent matches, weighted so the newest count most, and a side appears only when the player
has enough charted serves there for the share to be mostly signal rather than sampling
noise. Under it, **side by side** gives serve points won and return points won a ring each:
both players start at
the foot and climb, one up the left and one up the right, so the comparison is which sweep
goes further. Every ring runs between the two figures printed at its ends — zero under the
foot, its ceiling over the top — so twice the arc is twice the number, within a ring. The
ceilings differ where a metric's own full is useless: returning is the half of tennis nobody
wins outright, so that ring ends at 67% rather than spending two thirds of its climb on ground
no player has stood on. Read those ends before comparing one ring to another. All of it costs resolution where two tour pros differ by a
point or two, which is why each player's figure stands on their own side of the ring, the side
their arc climbs.

Only those two get rings, because a ring only works for a number with a real zero and a
reachable ceiling. Both are withheld below a coverage floor: they are career charted rates with
no opponent adjustment, and off a single charted match a qualifier was printing a serve figure
near the best in the draw.

One more figure prints beside them, in each player's own column under their shots per point:
**variety**, how far their shot choices stray from tour norms, in bits. A second one used to —
shot selection, the swing in a player's aggression across situations — and it went the same way
as the shot-quality verdict, for the same reason: two thirds of its spread was the player's own
baseline aggression, which the triggers section prints in plain percent further down, and it
correlated −0.81 with rally length. Its leaderboard was really a serve-volley leaderboard;
restricted to rally-only lead-ups Rafter fell from the top of the tour to below the median.

Bits are not a unit anyone arrives knowing, so the section can open a note that defines the
figure, glosses the unit, and says where the charted tour sits on it: half of it falls inside a
band about a third of a bit wide, which is what makes "3.2 bits" mean something. The gloss earns its place, because bits compound — every
extra bit is a shot half as likely again, so a gap that looks small is not. Those bands are
read off the built table when the panel opens rather than written into the prose, so they
cannot go stale against a rebuild. Nothing is converted to a rank or a percentile: the figures
print in the units they are measured in, so the distance between two players is the distance
you read.

Below the rings the sections run in the order a point does. **Off the return** comes first —
what the server does with the ball their serve comes back as, split by service court and return
depth — since it is built out of the serve the section above it just described. Then **court
patterns**, the mid-rally exchange, written in plain English:
`drive into the BH corner → crosscourt BH slice (1.6× the tour)`. Below them,
**shot-making triggers** are written in shot tokens: `serve wide · BH slice→3`, with a bar
under each cue: its length is how often that cue makes them go for a finishing shot, the
colour change is how much of that landed, and the tick marks the player's rate with no cue at
all. A cue is shown only if it clears a false-discovery correction across every context that
player was screened on, and holds its sign in both halves of their charted matches. The first
bar in each player's column is that player with no cue at all — their rate over every rally
stroke they hit, drawn on the same scale and from the same left edge — so the section's whole
claim is one glance: this is the rate, and these are the lead-ups that move it. Click the
**ball path** toggle under either to see it drawn on a small court. The drawer carries a
short "How to read the shot notation" key of its own, so the reference below is only here
for when you want the exact semantics.

<details>
<summary><b>The full reference</b> — patterns, trigger tokens, the court diagram, zone resolution, handedness</summary>

### Court patterns

A pattern is the player's answer to one incoming ball: the state (the ball's character and
the zone it lands in) and the response (wing, shot type, and line). The multiplier compares
how often the player picks that response to how often the tour picks it **from the same
spot**, so `1.6×` on a crosscourt slice means a genuine preference rather than just that
slices happen — and the tour it compares against is weighted to the player's own era, because
the game changes enough across the charted decades that a pre-2000 slicer measured against a
pooled field is mostly being told what decade they played in. The share the multiplier is taken
against prints beside it, since `1.6×` off a quarter of the field and `1.6×` off one percent are
different claims. The count prints as `n=277/970`: how often they play it, out of how often they
face the ball.

The payoff (`wins 52% ▲5 vs 47%`) is a separate claim: how often the point ends up theirs after
that response, against their own rate answering that same ball however else they answer it. It
used to be measured against the tour's rate for that response, which mostly ranked players
rather than choices — that gap runs about +0.43 with a player's overall serve-plus-return rate,
so the strongest players beat the tour on nearly every pattern they own whatever the tactic is
worth. The multiplier is the choice, the payoff is what it earns. Two families appear: **off the return**,
which is what the server does with their first ball after the serve, split by the charted depth
of the return (short / mid / deep), and the rally patterns that follow it.

Zones in a pattern are named by the **player's own hands**: "the BH corner" is that
player's backhand corner whether they are left- or right-handed. Run-around shots get their
tennis names, so a forehand played from the backhand corner is `inside-out` on the diagonal
and `inside-in` down the line. Every pattern shown repeated in both halves of the player's
charted matches; one-off quirks are filtered out.

### The trigger tokens

Each stroke is one token:

- **Wing and type.** `FH` / `BH` is the forehand or backhand wing the player actually hit
  with. The type is `drive` (flat or topspin), `slice` (slice or chip), `net` (volley,
  overhead, or half-volley), or `shot` when the type was not charted. These group a finer
  set in the raw notation, which also records drop shots, lobs, overheads, and so on.
- **Direction.** `→1` / `→2` / `→3` is the third of the court the ball was sent to, named
  relative to the **player's own hands** — mirrored for a left-hander, so one token string
  means one piece of tennis whoever played it. The raw notation names fixed thirds by the
  right-hander convention, which would make a lefty's crosscourt forehand and a righty's read
  as different shots and their mirror images read as the same one. `→·` means the direction
  was not charted.
- **Serves.** A serve is written as its target: `serve wide`, `serve body`, or `serve T`.

A trigger reads as a lead-up, the player's shot then the opponent's reply, and asks what
that cue provokes. The framework groups a player's point-ending shots as one behavioral
unit, the **aggressive shot**: a winner, their own unforced error, or a shot that forced
the reply into an error. All three mean they went for the finish, and only the execution
differed. "Aggressive" is the **aggressive shot frequency** the cue provokes — how often a
stroke there is one — and "converts" is the share that paid, winners and forced errors
together. A cue that raises the frequency but sinks conversion is a trap, and they take the
bait.

That numerator matches the one behind
[Aggression Score](https://www.tennisabstract.com/blog/2015/08/31/measuring-wta-tactics-with-aggression-score/).
It's a change from the narrower winner-plus-unforced reading used until 2026-08-05;
[`shot_triggers`](experiments/shot_triggers/) carries the split-half test that settled it.

### The court diagram

The diagram is a **placement map**, not a flight path: it marks where each ball landed and
joins the points in order, faint first and bold last. It comes in two flavors:

- **A pattern** draws the incoming ball landing on the near half, the player's side, so
  "into the BH corner" points where you'd expect, and the response, bold, landing up top.
  For return patterns the incoming bounce sits short, mid-court, or deep to match the
  charted return depth.
- **A trigger sequence** plays out from the near baseline, bounces alternating ends, with
  the small dot anchoring the first stroke (the server's contact when it starts with a
  serve). The notation does not record deuce or ad court, so serves assume the deuce court.

### Zones and how fine the charting really is

The placement is **coarse on purpose**, and the diagram shows only what was charted:

- **Three lateral zones.** Direction is recorded as one of three thirds, not a continuous
  spot, so two shots into different parts of the same third are the same zone. Within a
  third the diagram cannot separate a sharp crosscourt from a safer one.
- **Lines come from zone pairs.** A single zone code never says crosscourt or down the
  line, but a pattern knows both ends: the zone the ball arrived in fixes where the player
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

For **court patterns**, handedness is already folded in. The zones are flipped for
left-handers before anything is counted or compared, so "drive into the BH corner" means the
same tennis problem for Nadal as for Federer, and the comparison against the tour is apples
to apples. Without the flip, a lefty answering his forehand corner with a forehand posts a
huge, meaningless lift against a mostly right-handed tour.

The **trigger tokens** keep the raw convention: `→1` / `→2` / `→3` are fixed thirds named
by a right-hander's wings (`1` = a righty's forehand corner). The ball is drawn where it
physically went, so the diagram itself never needs adjusting. Just remember that for a
left-hander, `→3` is their forehand side.

</details>

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
docs/                  # the live Love All site (Pages)
```

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

<details>
<summary><b>Tournament tiering and coverage methodology</b> — where the tier column comes from, and why "coverage" needs a denominator</summary>

### Tournament tiering

The raw data has no tier field, so `analysis/tiers.py` derives one from the
free-text tournament name (Grand Slam / Masters-WTA 1000 / Tour Finals / Tour
250-500 / Team event / Other). ~99.8% of matches classify. Note: 250 vs 500 is
deliberately **not** split, because even Sackmann's authoritative ATP data collapses
them into one level.

The live site does need the split, to know which events to serve, so it takes levels from
the Wikipedia calendar feed (`live/feeds.py`) instead. That feed covers the current season
only and is deliberately kept out of `tiers.py`, so the tier column over 65 years of charted
matches stays as honest, and as stable, as the source data allows. Backfilling the calendar
season by season is the nearest route to a tier column that isn't name-derived. The season
pages carry the same schedule tables back to 1990, but every era labels its levels
differently (`Championship Series`, `ATP Masters Series`, `Tier I`, `Premier Mandatory`),
and the older pages don't always print a draw size, so it needs an era vocabulary rather
than a re-run.

One limit of the name lists: they carry no year, so an event that changed level keeps the
one the list gives it. Hamburg, Charleston and Tokyo sit in the 1000 bucket for seasons in
which they were 500s, about 90 matches between them, and the WTA events that move between
1000 and 500 from year to year add more.

### Coverage methodology

"Coverage" means **charted ÷ played**, not a raw charted count, so it needs a
denominator. The two we use are structural, true without any external results
data, and we keep men and women in separate figures throughout (every figure is
rendered as a `*_men.png` / `*_women.png` pair):

- **Grand Slams** — a singles main draw is always 128 players = **127 matches**, so coverage is `charted / 127` per slam-year-gender.
  Valid for all four slams since 1990.
- **Masters 1000 / WTA 1000** — draws vary (56 / 96 / 128), so there is no fixed
  full-draw denominator. The late rounds are invariant, though: every draw has
  R16=8, QF=4, SF=2, F=1 = **15 matches**. We report `charted / 15` from the
  round of 16 onward.

Two findings fall straight out: nothing is fully charted (best slam draw ≈ 50%),
and charting skews hard to the later rounds (slam finals 74–91% vs. R128 ~5%).

Two things to know when reading the figures. Denominators count only the events *present in
the charted data*, so a 1000-level event nobody charted is missing from the grid rather than
showing as 0%. And the tier column is name-derived and year-blind, as above.

Extending true coverage to the 250/500 tiers, or to full 1000 draws instead of the last 15
matches, needs a played-match count per event. The Wikipedia calendar feed already carries
one — a draw of N players is exactly N−1 matches — but only for the current season, and its
sizes are advisory: one 2026 row claims a 48-player field for a draw of 32. On the live path
a parsed draw is only trusted once it agrees with ESPN about who plays whom, and no
historical season has a live feed to check against. So the backfill is the prerequisite, and
it needs its own validation story rather than the one `live/feeds.py` uses.

</details>

## Attribution & license

The underlying data is © the Match Charting Project contributors, licensed
**CC BY-NC-SA 4.0** (attribution required, **non-commercial** use only). This
repository's *code* is MIT-licensed; the *data* it downloads remains under the
Match Charting Project license. Please credit the Match Charting Project in any
derived work.

- Data: https://github.com/JeffSackmann/tennis_MatchChartingProject
- License: https://creativecommons.org/licenses/by-nc-sa/4.0/
