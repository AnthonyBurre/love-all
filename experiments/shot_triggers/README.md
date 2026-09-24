# Shot-making triggers: what raises a player's aggressive shot frequency

`shot_patterns` keeps two separate books on every player: the lead-ups that
precede their **winners** and the lead-ups that precede their **unforced
errors**. This experiment asks whether those are really two books. A winner and
an unforced error share a decision (the player went for the finish) and differ only
in execution. If the same contexts rank high in both lists, the unit is the
**aggressive shot**, and the outcome is conversion.

Framed that way, it gives three things the separate lists can't:

1. **Trigger patterns** — per context, the player's **aggressive shot frequency**
   (point-ending shots per stroke) against their own baseline, i.e. which sequences
   make them go for the finish.
2. **Traps and green lights** — trigger contexts split by *conversion* (the share of
   those shots that paid) against the player's own conversion baseline. High
   frequency with low conversion is a trap: a sequence that draws them into a
   difficult finishing shot they don't make. A player with **no trap contexts** only
   gets more aggressive where it pays.
3. **Pattern immunity** — σ, the true between-context spread of a player's aggressive
   shot frequency (beta-binomial method of moments, so the binomial noise floor is
   subtracted and charting volume doesn't distort it). σ ≈ 0 means the decision
   doesn't depend on context; a large σ means strongly cue-driven.

## What "aggressive shot frequency" means here

How often a player's shot is an aggressive, point-ending one rather than a rally
ball. A stroke counts three ways:

- a **winner**,
- their own **unforced error**, or
- a shot that survived and **forced the reply into an error**.

Conversion is the share that paid: `(winners + induced forced errors) / all three`.
That matches the numerator behind
[Aggression Score](https://www.tennisabstract.com/blog/2015/08/31/measuring-wta-tactics-with-aggression-score/)
(Lowell West, via the Match Charting Project), so the figures here are on the
same footing as published ones.

Including induced forced errors needs justifying, since forced/unforced is the most
subjective call in the notation and the extra events could be noise. The report tests
the wide numerator against the narrower winners-plus-unforced reading, the
**finishing shot frequency**:

| | finishing (w+ue) | aggressive (+induced FE) |
|---|--:|--:|
| split-half r across ~12.5k contexts | +0.762 | **+0.811** |
| per-player median r | +0.608 | **+0.699** |
| players it is more reliable for | 16% | **84%** |

Matches are split at random into halves and each well-supported context measured
twice, so charter disagreement sits inside the noise this is testing. The wider
numerator replicates better, and does it while carrying a higher binomial noise
floor (base rate 18.0% → 22.9%). Player rankings barely move (r = +0.99), but the
composition does: induced forced errors run from 14% of a player's aggressive
shots (Opelka) to 34% (Santoro), so the narrow numerator under-credits players whose
aggression works through pressure rather than clean winners. The cue lists move most:
traps fall from 137 to 115, because under the narrow reading a shot that forced an
error counts as neither success nor aggression, which looks like low conversion and
earns a false trap label.

The definition lives in one place, `shots/notation.py:aggressive_shot`, and every
experiment that counts these imports it.

## Method

Same counting machinery as `shot_patterns` (two-shot lead-up context from the
`shot_language` tokens; the player's stroke marked winner `*` / unforced `@` /
forced `#`). A stroke marked `#` is an error its hitter was forced into, so it
counts for whoever forced it (the previous stroke), not against them. Per qualifying
player: context frequency and conversion tables, the winner-rate × error-rate
correlation across contexts (the "same book?" test), the σ dispersion score, and the
trap/green-light split. Counting only, no model.

## Opening sequences by serve side

The pooled contexts average over the service court, which hides structure in the
opening: a wide serve opens a right-hander's forehand in the deuce court and their
backhand in the ad court, so the same serve token means different things on the two
sides. A final section splits the aggressive shots within the first four plies (the
**return**, after the serve; the **serve+1**, after serve and return; the
**return+1**, after return and serve+1) by deuce/ad court, and scores each context
against the player's own baseline *for that shot and side*. Deeper rally contexts stay
pooled, where samples are already thin.

The output is per-player favorable (green) and trap opening sequences, separated
by serving vs returning role and by side, with per-side denominators. Full rows in
`reports/shot_triggers_openings.csv`; the report shows the marquee players. It
recovers known patterns unprompted (Nadal's deuce-court `serve wide` serve+1 runs at
2.5× his deuce serve+1 norm) and finds side-specific traps a pooled view can't (a
sequence that baits a player only when they serve to one court).

This section is screened the same way the pooled table is. Each `(player, side,
anchor)` group splits into the same two match-hash folds. One fold discovers (exact
binomial tail against that fold's group baseline, Benjamini-Hochberg at q=0.10 across
every context it could test, then a `TRIGGER_LIFT` lift), and the other confirms and
supplies every number shown. The group is the correction
family rather than the player, because a deuce serve+1 cue only ever competed
against other deuce serve+1 contexts.

The screen is expensive here: **484 raw rows over 171 players become 217 over 104.**
Of those, 118 clear from both directions and 99 from one. Across the 99 (the clean
out-of-sample read), the mean lift falls from 1.69× where it was found to
**1.31× where it was measured, 45% of the discovered edge**. `court_response` and
`rally_patterns` both keep about half on the same kind of test, over different
features and different screens.

These rows ship to the site as the panel's **opening cues by court** section. The
pooled cues ship too and include opening lead-ups on purpose: the pooled row says a
lead-up raises the player's aggression, and the court-split row says which service
court does it. The panel shows them next to each other.

## Limitations

- **"Aggressive shot" is a proxy.** Not every unforced error is a failed
  finishing shot (some are routine misses), and some winners are gifts. At our
  token resolution this is the best available proxy for shot-making risk; the
  README of `shot_patterns` carries the same coarseness caveats.
- **Split-half doesn't catch shared bias.** The comparison above shows charters
  don't disagree *with each other* enough to drown the induced-forced-error
  signal. If they collectively over-call "forced" for one kind of player, both
  definitions inherit that and this test would not show it.
- **Conversion is context-selected.** Comparing conversion across contexts
  within one player is fair; comparing conversion across players also reflects
  shot selection, opposition, and charting coverage.
- σ needs many well-populated contexts, so the immunity leaderboard is
  restricted to heavily-charted players.

Run: `python experiments/shot_triggers/run.py` → `reports/shot_triggers.md`,
`reports/shot_triggers.csv`, `reports/shot_triggers_openings.csv`,
`reports/figures/shot_triggers.png`.
