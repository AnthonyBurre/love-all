# Serve+1: the server's third ball

`court_response` already profiles this shot. Its "off the return" family asks
what the server does with the ball the return gives back, keyed by the return's
stroke kind, the zone it landed in, and its charted depth. It pools the two
service courts, and that pooling is not free.

A wide serve opens the forehand in the deuce court and the backhand in the ad
court. So "mid-depth drive return into the middle" is not one situation — it is
two, arriving off different serves, at different angles, with the server
recovering from opposite corners. Nadal's pooled reading is a crosscourt forehand
at 1.7x. Split by court, the same description is a **crosscourt forehand on the
deuce side** (n=3,202) and a **forehand down the line on the ad side**
(n=2,937). The pooled number is the average of two different shots and it names
neither.

This experiment does not change `court_response`. It re-asks the same question at
a finer state and lets each player's coverage decide how fine.

## Three tiers, chosen by coverage

| tier | state |
| --- | --- |
| `full` | serve side × serve direction × return kind × zone × depth |
| `side` | serve side × return kind × zone × depth |
| `pooled` | return kind × zone × depth — `court_response`'s state |

Every observation is counted into all three. A player is then assigned the finest
tier their coverage funds: `MIN_TIER_STATES` (4) distinct states with
`MIN_STATE` (80) observations each.

That test is deliberately about coverage and nothing else, and it runs **before
any lift is computed**. Picking the tier that surfaced the most patterns would be
picking the resolution that flattered the player, and the both-halves replication
gate does not fully undo that kind of selection. The cost is visible in the
numbers: 116 men clear the gates on at least one full-tier pattern, but only 90
are assigned the full tier, because the other 26 got there on a single state.

Everything else is `court_response`'s method, imported from that module rather
than copied — hand-relative zones, the reference lane that separates crosscourt
from down-the-line, shrunk lift against the field in the same state, the payoff,
and the replication gate. The two experiments' `pooled` rows mean the same thing
and read side by side.

## What it found

**Tier assignment.** 90 men and 53 women fund the full state; 57 and 61 the side
state; the rest stay pooled — mostly entities with a handful of charted matches,
which is why only 181 of those 1,443 go on to surface anything. The promotion is
close to lossless: 88 of the 90 men and 52 of the 53 women assigned the full tier
surface a pattern at it.

770 patterns across 434 players — 277 at full resolution, 211 side-only, 282
pooled. That is 85% of `court_response`'s `ret` pattern count, with two thirds of
it now side-specific.

**The serve direction is nearly free.** The full tier needs the serve's direction
charted, and only 87 men's and 120 women's observations lack it — under a tenth
of a percent. Requiring the return's *depth* has already selected points from
charters working at full detail, and those charters record the serve.

**Court disagreements.** 362 situations across 139 men, and 235 across 121 women,
where both courts are independently well charted and the player's most-played
answer differs between them. These are exactly what a pooled state cannot report:
it names whichever response won the average and buries the other. Sampras answers
the same mid-depth return with a crosscourt backhand volley on the deuce side and
a backhand volley down the line on the ad side. Kerber's ad-court wide serve into
a mid-depth return draws a crosscourt backhand at 3.7x.

**It holds up.** Full-tier split-half r = 0.85 (men) / 0.69 (women) over 9,120
cells — the finest state, where the counts are thinnest and the claim boldest.

## Run

```
uv run python experiments/serve_plus_one/run.py
```

Writes `reports/serve_plus_one.md`, `reports/serve_plus_one_players.csv` (one row
per surfaced pattern, carrying `tier`, `serve_side` and `serve_dir` alongside
`court_response`'s columns), and `reports/figures/serve_plus_one_tiers.png`.

## On the site

This feeds the matchup panel's **off the return** section, in place of
`court_response`'s `ret` rows. `court_response` still ships the **court patterns**
section from its `rally` family, and still reports its own `ret` family in
`reports/court_response.md` — it simply no longer feeds the panel.

The card names its own resolution, so a reader can see which one they are looking
at: "deuce court, T serve · mid-depth drive return into the middle" against the
pooled "mid-depth drive return into the middle". The court drawing gains the serve
itself, which is what makes the side legible at a glance.
