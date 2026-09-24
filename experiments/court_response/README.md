# Court-state response profiles

What does a player do with a given incoming ball? The state is the ball only:
its character (drive / slice / net ball / drop-lob) and the zone it lands in,
named relative to the receiver's own hands. The response is the player's
decision: wing, shot type, and the line taken (crosscourt, down the line,
through the middle, with run-around shots named inside-out / inside-in).
Everything upstream of the incoming ball is ignored on purpose: the reaction to
a slice into the backhand corner should mostly not depend on how that ball got
there. How far "mostly" stretches is measured (see [where the state is still too
coarse](#where-the-state-is-still-too-coarse)).

Two state families come from one pass. **Rally** states are depth-agnostic and
cover every rally pair. **Return** states add the charted return depth (short /
mid / deep) and cover only the server's shot 3, the one spot where depth is
charted often enough (~74% of returns, ~19% of later balls) to condition on.
That family picks out the serve-and-volleyers clearly: Edberg's crosscourt backhand
volley behind a mid-depth return runs at 25x the field, Navratilova's at 75x.

Each pattern also carries its **payoff**: the player's point-win rate after
playing that response (shrunk toward the field's), next to the field's rate
playing the same response to the same ball. Choice and execution stay separate
claims: Djokovic picks the backhand down the line 1.4x as often *and* wins
52% with it vs the tour's 46%, while an overused pet shot shows up as a lift
with a negative payoff gap.

## Why

Conditioning on the opponent's full previous token and ranking by raw lift
surfaces three kinds of junk:

- generic rally geometry (the same crosscourt pair headlines 22% of the 313
  player cards),
- uncharted-direction artifacts (Djokovic's top signature comes out as
  `FH drive→· → FH drive→·`),
- handedness posing as style (a lefty answering his forehand corner with a
  forehand posts a 20x lift against a right-handed field).

This framing fixes all three: `·` tokens are excluded, zones are normalized by
the receiver's hand, and patterns are ranked by evidence (count x log2 lift)
so a tendency backed by thousands of shots outranks a rare quirk with a
flashier ratio. A pattern is only surfaced if it repeats in both halves of the
player's charted matches.

## Zone geometry

Direction codes name fixed thirds of the court by the right-hander convention
(code 1 = a righty's forehand corner). The two ends face each other, so a
reply to the same code travels the diagonal (crosscourt) and a reply to the
mirrored code goes down the line. For balls through the middle, the hitter's
wing fixes the reference lane. The lefty flip was verified empirically: Nadal
answers code-1 balls 82% with the backhand and code-3 balls 98% with the
forehand.

## Run

```bash
uv run python experiments/court_response/run.py
```

Reads `data/tennis.duckdb` (all charted points, no sampling, since the split-half
gate needs the volume). Writes `reports/court_response.md`,
`reports/court_response_players.csv` (one row per surfaced pattern, with
`inc_code`/`resp_code` mapping each pattern back to physical zones so the
site's court renderer can draw it), and
`reports/figures/court_response_stability.png`.

The CSV feeds the live site: `site build-insights` ships it as the
`player_patterns` table in `insights.duckdb`, and the matchup drawer's "court
patterns" / "off the return" panels render it (drawn by `pairSvg` in
`docs/js/court.js`). The CI insights workflow runs this experiment weekly.

## How a pattern is screened

Every figure shown is **held out**. A player's matches split in two and each fold
takes a turn discovering: an exact binomial tail against the field's share for
that state, Benjamini-Hochberg at q=0.10 across every cell that fold screened for
that player, then a shrunk lift ≥1.4 to be a candidate. The lift, payoff and
counts are read off the other fold, which needs to still show ≥1.15 to confirm.
Without the correction the screen would test a median of 17 candidates per player
and up to 208, about 85,000 across the tour.

The correction costs little here: it removes roughly one pattern in eight, leaving
about 2,400 across some 750 players. These cells were already stable (see the r
below), so it mostly trims the thin tail. On the ~800 patterns confirmed from a
single direction, where the shown lift comes from a fold with no vote, **about half
of the discovered edge survives out of sample**, close to what `rally_patterns`
measures on a different screen. That suggests the figure belongs to this kind of
search rather than to either experiment. `reports/court_response.md` has the exact
counts from the latest run.

## Where the state is still too coarse

A cell pools the serve+1 ball with the same-described ball at shot 11. For **691
of 4,218** well-supported cells (16.4%, against 0 of 5,040 on a coin-flip control),
the response a player picks differs measurably between the two, so those cells
average two situations. The likely mechanism is the ceiling
described at the end of this README: "a drive into the BH corner" arriving off a
return, with the server still recovering, is not the same ball as one at shot 11.
Splitting those cells isn't implemented.

## Result

Split-half stability r = +0.73 (men) / +0.69 (women) across ~43k player-state-response
cells (rally and return families). The most-shared headline pattern covers 12% of men's
profiles (against 22% when conditioning on the full previous token), and it is a style
choice (the crosscourt slice from the backhand corner) rather than forced geometry. The
high-volume profiles read as scouting reports, and all of them survive the corrected
screen: Federer's crosscourt backhand slice (1.67x), Djokovic's backhand down the line
(1.44x), Nadal's run-around forehand from the middle (1.49x).

Lifts are taken against a field weighted to the player's own era (see `ERAS` and
`era_baseline` in run.py). Graf's crosscourt backhand slice reads 7.3x against the pooled
corpus and **3.2x** against the field she actually played: among women answering a drive
into the backhand corner, that slice runs 23.6% pre-2000 against 5.7% in the 2000s, so
most of the pooled lift was the decade rather than the player.

## The ceiling on what a pattern can mean

**The state is coarser than the tactic it names.** It carries the incoming ball's
character (drive / slice / net / drop-lob) and the third of the court it lands in, and
nothing else: no height, spin or speed, and no record of where the striker was
standing. The charting doesn't record those.

"A drive into the BH corner" pools a deep heavy topspin ball that forces a defensive
slice with a short one that invites a step-around forehand. Those call for opposite
answers, and the card reports the mix as one choice. So a response that's largely forced
reads as a preference, and the lift is partly about which of the two balls the player
tends to receive, i.e. about their opponents.

That's why the payoff is baselined against the player's own rate on the same ball rather
than the tour's: both sides inherit the same mix, so it largely cancels. It doesn't cancel
for the lift.
