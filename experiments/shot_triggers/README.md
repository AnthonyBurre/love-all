# Shot-making triggers: what raises a player's aggressive shot frequency

`shot_patterns` keeps two separate books on every player: the lead-ups that
precede their **winners** and the lead-ups that precede their **unforced
errors**. This experiment asks whether those are really two books at all. A
winner and an unforced error share a decision — the player went for the finish
— and differ only in execution. If the same contexts sit high in both lists,
the behavioral unit is the **aggressive shot**, and outcome is conversion.

Recasting in those terms gives three things the separate lists can't:

1. **Trigger patterns** — per context, the player's **aggressive shot
   frequency** (point-ending shots per stroke) vs their own baseline: which
   sequences make them go for the finish.
2. **Traps vs green lights** — among their trigger contexts, split by
   *conversion* (the share of those shots that paid) against their own
   conversion baseline. High frequency with low conversion is exactly "a sequence that
   pulls them into a difficult finishing shot": they take the bait and don't
   cash it. A player with **no trap contexts** is immune in the sense that
   matters — their extra aggression shows up only where it pays.
3. **Pattern-immunity** — σ, the true between-context spread of a player's
   aggressive shot frequency (beta-binomial method of moments, so the binomial
   noise floor is subtracted and charting volume doesn't distort the
   comparison). σ ≈ 0 means the decision looks context-independent (nothing
   baits them *or* greenlights them); large σ means strongly cue-driven.

## What "aggressive shot frequency" means here

The term is the standard one: how often a player's shot is an aggressive,
point-ending one rather than a rally ball. A stroke counts three ways —

- a **winner**,
- their own **unforced error**, or
- a shot that survived and **forced the reply into an error**.

Conversion is the share that paid: `(winners + induced forced errors) / all three`.
That matches the numerator behind
[Aggression Score](https://www.tennisabstract.com/blog/2015/08/31/measuring-wta-tactics-with-aggression-score/)
(Lowell West, via the Match Charting Project), so the figures here are on the
same footing as published ones.

Until 2026-08-05 this experiment left induced forced errors out, on the reasoning
that being beaten isn't a shot the opponent chose. Call that narrower reading the
**finishing shot frequency**. The report now carries a section testing the two
against each other, because the reasonable worry was that forced/unforced is the
most charter-subjective call in the notation and the extra events might be noise:

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
shots (Opelka) to 34% (Santoro), so the old numerator quietly under-credited
players whose aggression works by pressure rather than clean winners. The cue
lists move most of all — traps fall from 137 to 115, because a shot that forced
an error used to count as neither success nor aggression, which read as low
conversion and drew a trap label it hadn't earned.

The definition lives in one place, `shots/notation.py:aggressive_shot`, and every
experiment that counts these imports it.

## Method

Same counting machinery as `shot_patterns` (two-shot lead-up context from the
`shot_language` tokens; the player's stroke marked winner `*` / unforced `@` /
forced `#`). A stroke marked `#` is an error its hitter was forced into, so it
counts for whoever forced it — the previous stroke — not against them. Per
qualifying player: context frequency/conversion tables, the winner-rate ×
error-rate correlation across contexts (the "are these the same book?" test), the
σ dispersion score, and the trap/green-light split. Pure counting — no model.

## Opening sequences by serve side

The pooled contexts above average over the court the point was served to, which
hides real structure in the opening: a wide serve opens a right-hander's forehand
in the deuce court and their backhand in the ad court, so the same serve token
means different things on the two sides. A final section splits the aggressive
shots that sit entirely within the first four plies — the **return** (lead-up: the serve),
the **serve+1** (serve, return) and the **return+1** (return, serve+1) — by
deuce/ad court, and scores each context against the player's own baseline *for
that same shot and side*. Everything deeper in the rally stays pooled, where the
sample per context is thin enough already.

The output is per-player favorable (green) and trap opening sequences, separated
by serving vs returning role and by side, with per-side denominators. Full rows in
`reports/shot_triggers_openings.csv`; the report shows the marquee players. This
reproduces known shapes without being told them — Nadal's deuce-court `serve wide`
serve+1 runs at 2.5× his deuce serve+1 norm — and separates side-specific traps a
pooled view can't (a sequence that baits a player only when they serve to one court).

**This section was screened properly on 2026-08-29, and was not before.** It had
been a raw threshold screen since it was written: clear the support floor, clear
`TRIGGER_LIFT`, tag on the sign of the conversion gap. No multiplicity correction,
and every displayed figure computed on the data that had just selected the row —
while the pooled table above it had been FDR-corrected and cross-validated since
`tag_contexts` landed. One experiment, two tables, one of them screened.

Each `(player, side, anchor)` group now splits into the same two match-hash folds
the pooled screen uses. One fold discovers — exact binomial tail against that
fold's own group baseline, Benjamini-Hochberg at q=0.10 across every context it
could test, then a `TRIGGER_LIFT` lift to be a candidate — and the other confirms
and supplies every number shown. The group is the correction family rather than
the player, because a deuce serve+1 cue only ever competed against other deuce
serve+1 contexts.

It cost more than the same fix cost elsewhere: **484 rows over 171 players became
217 over 104.** Of those, 118 cleared from both directions and 99 from one, and
across that 99 — the clean out-of-sample read — the mean lift falls from 1.69× where
it was found to **1.31× where it was measured, 45% of the discovered edge**.
`court_response` measured 46% on the same kind of test and `rally_patterns` 50%,
over different features and different screens. Three independent readings of the
same number is the most useful thing to come out of any of this.

These rows ship to the site as the panel's **opening cues by court** section. The
pooled cues above still ship too and still contain opening lead-ups; that overlap
is deliberate. The pooled row says a lead-up raises the player's aggression, and
the court-split row says which of the two service courts is doing it — a refinement
rather than a contradiction, and the panel shows them adjacent so it reads that way.

## Honest limitations

- **"Aggressive shot" is a proxy.** Not every unforced error is a failed
  finishing shot (some are routine misses), and some winners are gifts. At our
  token resolution this is the honest available proxy for shot-making risk; the
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
