# Court-state response profiles

What does a player do with a given incoming ball? The state is the ball only:
its character (drive / slice / net ball / drop-lob) and the zone it lands in,
named relative to the receiver's own hands. The response is the player's
decision: wing, shot type, and the line taken (crosscourt, down the line,
through the middle, with run-around shots named inside-out / inside-in).
Everything upstream of the incoming ball is ignored on purpose — the reaction
to a slice into the backhand corner should not, mostly, depend on how that ball
got there. "Mostly" is doing work in that sentence and it is measured rather
than assumed: see [where it fails](#where-the-state-is-still-too-coarse).

Two state families come from one pass. **Rally** states are depth-agnostic and
cover every rally pair. **Return** states add the charted return depth (short /
mid / deep) and cover only the server's shot 3 — the one spot where depth is
charted often enough (~74% of returns, ~19% of later balls) to condition on.
That family catches the serve-and-volleyers cold: Edberg's crosscourt backhand
volley behind a mid-depth return runs at 25x the field, Navratilova's at 75x.

Each pattern also carries its **payoff**: the player's point-win rate after
playing that response (shrunk toward the field's), next to the field's rate
playing the same response to the same ball. Choice and execution stay separate
claims — Djokovic picks the backhand down the line 1.4x as often *and* wins
52% with it vs the tour's 46%, while an overused pet shot shows up as a lift
with a negative payoff gap.

## Why

The site's signature panel conditions on the opponent's full previous token
and ranks by raw lift. That surfaces three kinds of junk:

- generic rally geometry (the same crosscourt pair headlines 22% of the 313
  player cards),
- uncharted-direction artifacts (Djokovic's old top signature was
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

Reads `data/tennis.duckdb` (all charted points, no sampling — the split-half
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

Both halves of that landed on 2026-08-29 and neither was here before. The screen
had **no multiplicity correction at all** while testing a median of 17 candidates
per player and up to 208 — 87,080 across the tour — and it printed a lift computed
on the same pooled data its gates had just used to select the pattern. It was the
last pattern-mining screen in the repo doing either; `shot_triggers`,
`serve_plus_one` and `rally_patterns` were already corrected.

The cost was small, which is itself the finding. 2,804 patterns over 805 players
became **2,434 over 746** — the same correction took `deep_patterns` from 72 to 36.
These cells were already stable (see the r below), so it mostly trimmed the thin
tail. And on the 817 patterns confirmed from a single direction, where the shown
lift comes from a fold with no vote, **46% of the discovered edge survives out of
sample** — within a few points of what `rally_patterns` measured on a completely
different screen (50%), which suggests that number is a property of this kind of
search rather than of either experiment.

## Where the state is still too coarse

A cell pools the serve+1 ball with the same-described ball at shot 11. For **691
of 4,218** well-supported cells — 16.4%, against 0 of 5,040 on a coin-flip control
— the response a player picks differs measurably between the two, so those cells
average two situations and name neither. The likely mechanism is the ceiling
described at the end of this README: "a drive into the BH corner" arriving off a
return, with the server still recovering, is not the same ball as one at shot 11.

The fix is a heterogeneity pass over the survivors — split the cells that differ,
leave the rest pooled with evidence that pooling is justified, exactly the shape
`deep_patterns` used for its deuce/ad refinement. It costs no coverage and is a
natural third test in the family the screen already corrects across. **It is not
implemented. It is the next thing this experiment should do.**

## Result

Split-half stability r = +0.73 (men) / +0.69 (women) across ~43k
player-state-response cells (rally and return families). The most-shared headline pattern covers 12% of
men's profiles (vs 22% for the old signatures), and it is a genuine style
trait (choosing the crosscourt slice from the backhand corner) rather than
forced geometry. The high-volume profiles read as scouting reports, and all of
them survive the corrected screen: Federer's crosscourt backhand slice (1.67x),
Djokovic's backhand down the line (1.44x), Nadal's run-around forehand from the
middle (1.49x).

Lifts are taken against a field weighted to the player's own era (see `ERAS` and
`era_baseline` in run.py). Graf's crosscourt backhand slice reads 7.3x against the pooled
corpus and **3.2x** against the field she actually played: among women answering a drive
into the backhand corner, that slice runs 23.6% pre-2000 against 5.7% in the 2000s, so
most of the pooled lift was the decade rather than the player.

## The ceiling on what a pattern can mean

**The state is coarser than the tactic it names.** It carries the incoming ball's
character (drive / slice / net / drop-lob) and the third of the court it lands in, and
nothing else — no height, no spin, no speed, and no record of where the striker was
standing. The charting does not record those, so this is a ceiling rather than a
shortcut.

What that costs is specific: "a drive into the BH corner" pools a deep heavy topspin ball
that forces a defensive slice with a short floaty one that invites a step-around forehand.
Those are opposite situations demanding opposite answers, and the card reports the mix as
though it were one choice. So a response that is largely a *necessity* reads as a
*preference*, and the lift over the field is partly a statement about which of the two
balls that player tends to receive — which is a fact about their opponents.

The payoff column is the place this bites hardest, and is why it is baselined against the
player's own rate answering that same ball rather than against the tour's: both sides of
that comparison inherit the same mix, so the mix largely cancels. It does not cancel for
the lift, which has no such shelter.
