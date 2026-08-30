# Rally patterns: mining with the opening blinded out

Replaces `deep_patterns`. That experiment asked whether 3–4 shot patterns survive for
the most heavily charted players and answered yes, 36 of them across 15 players. The
answer did not hold up for two reasons, and this experiment is what is left after
fixing both.

**Most of it was the serve.** `deep_patterns` let a deep context sit anywhere in the
point, including inside the opening. Its own side-refinement pass counted how often
that happened, and reading those counts back: **71% of its gold patterns' occurrences
had a window reaching into the first four plies**, nine of the 36 were pure serve
sequences that cannot occur mid-rally at all, and all three of its depth-4 patterns
began with the serve. That is ground `shot_triggers`' openings section and
`serve_plus_one` already cover, at higher support and split by service court — which a
pooled deep context cannot do. Only 8 of the 36 still cleared the support floor on
their non-opening occurrences alone.

**Its effect sizes were measured on the data that selected them.** The screen gated on
a pattern beating its parent in *both* match-hash halves, then displayed the lift
computed over all of it. `shot_triggers` does not do this — its figures are the
held-out ones — so the starred tier was the one thing on the panel held to a lower
standard than the rows around it.

## What this does instead

Blind the first four plies: serve, return, serve+1, return+1. That is exactly the span
`shot_triggers` covers in its openings section, so the two partition the point with no
overlap and no gap — the opening is its book, the rally is this one.

Two things follow from the blind. The first is **pooling**. With the serve out of the
window there is no reason a player's serving points, returning points, deuce points and
ad points should be separate populations, and pooling them is what funds a per-player
context table at all. `deep_patterns` pooled them too, but justified it by citing
`serve_side`'s model evaluation, which is a different test on different data. Here it is
asked of the cells actually being pooled, against a coin-flip split of the same cells as
the control: **2 of 1,441 men's cells reject on serving-vs-returning role, 0 of 1,659 on
deuce-vs-ad; women reject 0 of 523 and 0 of 582.** So the pooling is measured rather
than assumed, and the Holm-corrected Fisher pass `deep_patterns` ran over every survivor
to check the same thing is gone.

The second is that **blinding is a knob, not a choice**, so it is swept. Under `window`
no part of the context or the struck ball touches the opening. Under `target` only the
struck ball has to clear it and the context may reach back — roughly what
`deep_patterns` did, and in fact still stricter, since that screen put no floor on the
struck ball either. The gap between the two arms is how much of a deep-pattern yield is
the serve.

## The split

Two folds of a player's matches, each taking a turn. The discovery fold runs the whole
screen — support floor, a ≥1.3× lift over the pattern's own parent, an exact binomial
against the parent rate, and Benjamini-Hochberg at q=0.10 across every context that fold
screened for that player, all three depths sharing one family because they are one
search. The rate, lift, conversion and green/trap tag are then read off the other fold,
which had no vote. A pattern whose two directions disagree about the tag is dropped.

One change to the parent that matters more than it sounds. `deep_patterns` looked its
parent up in a table built over all of that parent's own occurrences — a wider and
differently distributed set of strokes than the child's, since the child could only occur
where a K-shot window was legal. Part of every parent lift it reported was therefore the
two contexts being measured on different populations. Here the parent is derived from the
child cells by dropping the leading token, so both sides of every ratio are the same
strokes and the only difference between them is the token the gate is asking about.

## What it found

**Deep patterns were the serve.** Of 1,752 serve-blind 3-shot candidates screened, two
survive — one for Nadal, one for Kerber. At four shots, 362 candidates and none. Let the
context reach back into the opening and the same screen returns 15 at three shots and 2
at four: seven times as many patterns from a candidate pool only three times larger. And
what it buys does not hold up. Those three-shot survivors keep 33% of their discovered
edge out of sample where the same arm's two-shot patterns keep 65%, and 44% of their
evidence sits in occurrences whose context touches the opening.

**Two-shot rally patterns are real.** 109 discoveries across 62 players, 89 of them
surviving the two-fold dedup, and 89% replicate above their parent on the fold that had
no vote. That is the honest resolution of `context_length`'s verdict —
two shots of history is what this data supports, and blinding the opening does not
change where that ceiling sits.

**Half to two thirds of a discovered edge is real.** A pattern found at lift L posts
about `1 + 0.50(L − 1)` out of sample on serve-blind ground, and `1 + 0.65(L − 1)` with
the opening left in. The second is higher because opening contexts carry real serve
signal, not because the looser rule is better calibrated — at three shots it falls to
`1 + 0.33(L − 1)`, the worst of any arm big enough to quote. That shrinkage is the
reason the split exists, and it is the one figure here that generalises past tennis.

## Honest limitations

- **Everything is conditional on the point surviving the opening**, and how often that
  happens is intensely player-specific: 17% of Krajicek's points reach the fifth shot
  against 53% of Coria's. Blinding does not remove the serve from these profiles, it
  conditions on it — Karlovic's rally book is built from the points his serve failed to
  settle. This is selection, not noise, and blinding deeper makes it worse. Every
  profile ships its exposure next to it, and comparisons across players inherit the
  problem in a way comparisons within a player do not.
- **The screen is stricter than the one it replaces**, so the counts are not comparable
  to 36. A surviving pattern here rests on more evidence, not less.
- **Era-mixing is inherited.** A twenty-year career is one bag of strokes.
- **One numerator.** `deep_patterns` carried a shadow pass on the narrower
  finishing-shot reading; `shot_triggers` settled that question on far more support, and
  the multiplicity budget here goes to the blinding sweep instead.

## Run

```bash
uv run python experiments/rally_patterns/run.py
```

Writes `reports/rally_patterns.md`, `reports/rally_patterns.csv` (the shipped set),
`reports/rally_patterns_sweep.csv` (the yield and calibration grid),
`reports/rally_patterns_calibration.csv` (every discovery outcome, unfiltered) and
`reports/figures/rally_patterns.png`.

## On the site

`build-insights` ships `rally_patterns.csv` into the `player_triggers` table with
`depth > 2`, which the matchup drawer renders as the starred tier against "the shorter
pattern" — the same wiring `deep_patterns` used, unchanged. The tier is small now
because that is how much of it survived being asked properly.
