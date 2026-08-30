# Rally patterns: mining with the opening blinded out

How much pattern is there in a tennis rally once the serve can no longer explain it?
This screens 2-, 3- and 4-shot sequences for per-player tendencies with the first four
plies — serve, return, serve+1, return+1 — blinded out.

The blind is there because the opening is where this kind of mining breaks. A deep
context that sits anywhere in the point drifts into the serve, where it has less support
than the dedicated sections do and no idea which service court the point was played to,
even though a wide serve opens opposite wings on the two sides. `shot_triggers`' openings
section and `serve_plus_one` measure those shots properly; this measures what is left.

Two things follow from blinding.

**Pooling.** With the serve out of the window there is no reason a player's serving
points, returning points, deuce points and ad points should be separate populations, and
pooling them is what funds a per-player context table at all. That is asked of the cells
actually being pooled, against a coin-flip split of the same cells as a control: **2 of
1,441 men's cells reject on serving-vs-returning role, 0 of 1,659 on deuce-vs-ad; women
reject 0 of 523 and 0 of 582.** The pooling is measured rather than assumed.

**Blinding is a knob, so it is swept.** Under `window` no part of the context or the
struck ball touches the opening. Under `target` only the struck ball has to clear it and
the context may reach back. The gap between the two arms is how much of a deep-pattern
yield is really the serve.

## The split

Two folds of a player's matches, each taking a turn. The discovery fold runs the whole
screen — support floor, a ≥1.3× lift over the pattern's own parent, an exact binomial
against the parent rate, and Benjamini-Hochberg at q=0.10 across every context that fold
screened for that player, all three depths sharing one family because they are one
search. The rate, lift, conversion and green/trap tag are then read off the other fold,
which had no vote. A pattern whose two directions disagree about the tag is dropped.

The parent is derived from the child cells by dropping the leading token, so both sides
of every ratio are the same strokes and the only difference between them is the token the
gate is asking about. Looking the parent up in a table built over all of its own
occurrences would compare two differently distributed populations, since a child can only
occur where a K-shot window is legal.

## What it found

**Deep patterns were the serve.** Of 1,752 serve-blind 3-shot candidates screened, two
survive — one for Nadal, one for Kerber. At four shots, 362 candidates and none. Let the
context reach back into the opening and the same screen returns 15 at three shots and 2
at four: seven times as many patterns from a candidate pool only three times larger. What
that buys does not hold up. Those three-shot survivors keep 33% of their discovered edge
out of sample where the same arm's two-shot patterns keep 65%, and 44% of their evidence
sits in occurrences whose context touches the opening.

**Two-shot rally patterns are real.** 109 discoveries across 62 players, 89 surviving the
two-fold dedup, and 89% replicate above their parent on the fold that had no vote. Two
shots of history is what this data supports, matching `context_length`; blinding the
opening does not move that ceiling.

**Half to two thirds of a discovered edge is real.** A pattern found at lift L posts
about `1 + 0.50(L − 1)` out of sample on serve-blind ground, and `1 + 0.65(L − 1)` with
the opening left in. The second is higher because opening contexts carry real serve
signal, not because the looser rule is better calibrated — at three shots it falls to
`1 + 0.33(L − 1)`, the worst of any arm big enough to quote.

## Limitations

- **Everything is conditional on the point surviving the opening**, and how often that
  happens is intensely player-specific: 17% of Krajicek's points reach the fifth shot
  against 53% of Coria's. Blinding does not remove the serve from these profiles, it
  conditions on it — Karlovic's rally book is built from the points his serve failed to
  settle. This is selection, not noise, and blinding deeper makes it worse. Every profile
  ships its exposure next to it, and comparisons across players inherit the problem in a
  way comparisons within a player do not.
- **Era-mixing is inherited.** A twenty-year career is one bag of strokes.
- **One numerator.** `shot_triggers` settled aggressive-shot vs finishing-shot on far
  more support, so the multiplicity budget here goes to the blinding sweep instead.

## Run

```bash
uv run python experiments/rally_patterns/run.py
```

Writes `reports/rally_patterns.md`, `reports/rally_patterns.csv` (the shipped set),
`reports/rally_patterns_sweep.csv` (the yield and calibration grid),
`reports/rally_patterns_calibration.csv` (every discovery outcome, unfiltered) and
`reports/figures/rally_patterns.png`.

## On the site

Nothing from here ships. The drawer's starred 3–4 shot tier was retired on this
experiment's result: two of 1,752 three-shot candidates survive, and both belong to
retired players who appear in no draw. The experiment still runs weekly and still writes
`reports/rally_patterns.csv`, so the tier can come back if the charting ever funds it.
