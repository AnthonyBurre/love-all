# Serve placement — which tendencies are measurements

What can be safely said about where a player serves? `serve_side` answered the
descriptive half of that: deuce and ad are different shots, and it printed the
wide/body/T mix for the tour and five marquee players per tour. This folder
answers the measurement half. For each statistic a player card might carry, it
asks whether players differ on it by more than sampling noise, whether it
repeats in the other half of the same player's matches, and how much charted
data it needs before either is true.

The same machinery then answers three questions that follow from it: does a
player's placement hold match to match, does it move across a career, and does
it change on big points.

## What it finds

**Placement choice is a measurement; what the placement earns is not.** On the
deuce court's first serves, players' true spread in wide share is ±6.5% (men)
after sampling noise is removed, and the two halves of a player's matches agree
at r = +0.58. The payoff version of the same statistic — points won behind the T
minus behind the wide serve — has a true spread of only ±3.1% and split halves
that agree at r = +0.22. Reaching 80% signal takes about 860 charted first
serves on a side for the choice and about 11,000 for the payoff. "Serves wide on
the deuce court more than anyone" is printable; "wins more behind the T" is the
stat most worth wanting and least worth printing.

**A player is not a fixed coin, so the binomial sample-size rule is wrong by a
factor of four.** The observed split-half correlations sit well below what a
player who flipped one coin every match would produce. Closing that gap takes
3.7x the sampling variance, which is the same excess step 4 measures directly:
median per-match dispersion phi = 1.80, and 73% of profiles are overdispersed
beyond chance. Serve placement is re-decided per match, not merely executed.
Expecting each match at the player's rate against that returner's handedness
barely moves it (1.87 → 1.80), and expecting it at their rate that calendar year
moves it a little further (→ 1.64). Most of the movement is match-specific and
still unexplained. The per-player ranking is face-valid: Karlovic and Zverev sit
near the fixed-coin floor on the deuce court, while Nadal and Edberg are the
most restless in the ad court, which is where a lefty's wide serve and a
serve-volleyer's mix are the most opponent-dependent decisions they make.

**Careers move more than styles do.** Half of the long careers here (72 of 143
men) show an early-vs-late placement gap of 1.5x or more against a shuffled
split of their own matches, against the ~21% of long careers `career_splits`
finds stylistically evolved. Read the ratio next to the gap, though: a
heavily-charted career detects a tiny move because its null is tiny. Federer's
gap is 0.024 at 3.4x; Tim Henman's is 0.135, an ad-court T share falling from
46% to 31%.

**Break points move the tour barely and some players a lot.** Side-adjusted —
break points skew to the ad court, and the court matters far more than the score
— the pooled shift is +2.3% toward wide. But 58 of 247 men move beyond chance at
FDR 0.10, in both directions, so the tour average is players cancelling out.
Sampras goes 12 points wider on break points, Kyrgios 14.

**Recency is worth having, and it is worth less than it sounds.** Since careers
move, a card should arguably print recent matches rather than a career average.
How recent is a prediction question, so it is settled by prediction: hold out
each player's most recent 200+ charted first serves and score every windowing
rule on them. Most of what any rule gets wrong is the holdout's own sampling
noise (±4.4%); of the part the rule owns, the best one removes 5% for the men
and 7% for the women — the T-share error falls from 6.2% to 5.9% (men) and 7.3%
to 6.9% (women). The winner is not a cutoff but a **10-match half-life** over
the whole career, narrowly ahead of a hard "last 20 matches", and every rule
tested beats the flat career average. The gain concentrates exactly where step 5
says it should: among the careers flagged as drifted it is 2.4x (men) and 8x
(women) the gain on the stable ones, and it never costs anything on the stable
ones, which is why the rule is worth applying to everyone rather than branching
on a drift flag.

**The body serve is partly a charter's opinion.** Holding the player fixed and
varying who charted them, charters disagree about the body share by ±4.3% (men)
against a tour body share of 10%. Wide and T carry a smaller fingerprint
(±3.0%), which is why every headline above is stated in wide-versus-T terms.
Splitting the halves by *charter* instead of by match — so the fingerprint
counts against the statistic rather than for it — leaves the wide share
repeating at r = +0.56 against +0.58, so the stability is the player, not the
person typing.

**That disagreement is not symmetric between the tours, and the site treats them as
though it were.** The women's *wide* share carries a charter fingerprint of ±4.5% —
about the size of the men's *body* fingerprint, which is the disagreement that
disqualified the body share from being reported at all — against a true between-player
spread of ±7.9%. So roughly a third of the visible spread in a women's wide share is
who typed it, where for the men it is closer to a sixth. Nothing downstream accounts
for this: the panel applies one reliability gate, derived from the men's numbers, to
both tours, and prints the two identically.

This is a stated caveat rather than a per-tour gate. It is not a reason to withhold the
women's numbers — a third of the spread being charter noise still leaves two thirds that
is the player, which is why the split-half stability holds up — but a women's wide share
should be read as the coarser of the two measurements.

## Related experiments

- **`serve_side`** owns the descriptive split and stays the place to look up what a mix
  *is*; this adds the error bars.
- **`blind_reid`** finds the serve the weakest of three feature blocks for naming a
  player. That is discrimination *between* players, where reliability is a statement
  *within* one. A statistic can be perfectly stable per player and still identify nobody
  if its true spread is narrow, which is the serve's situation.
- **`career_splits`** decides whether a career becomes two entities in a 10-feature style
  space that already includes serve location. Step 5 narrows that design to placement
  alone, so it answers "did the serve move" rather than "did the player".

## Run

```bash
uv run python experiments/serve_tendencies/run.py
```

Reads `data/tennis.duckdb` — all charted points, no sampling — in one pass per
tour, about 8 seconds. Placement is read straight off the notation string rather
than through the full point decoder, since only the serve token is needed.
Writes `reports/serve_tendencies.md`, `reports/serve_tendencies_players.csv`
(one row per player, side and serve number, with the halves, dispersion and
drift columns, plus the `recent_*` block — the decay-weighted mix a card should
print, its effective sample size, its year span, and a `reliable` flag for
whether that sample clears the step-3 bar), `reports/serve_tendencies_leverage.csv`
(per-player break-point shifts), and two figures. Deterministic: the shuffled null is seeded per player
and the match list is sorted before shuffling.

## Method notes

- **Side** comes from the score parity rule in `shots/score.py`, as in
  `serve_side`. The `40-40` bucket landing only in the deuce court is a free
  check that the derivation holds.
- **True spread** is the observed variance across players minus the mean
  binomial sampling variance, so it does not reward thinly-charted players for
  scattering.
- **Sample-size rules** invert that: reliability at n is tau² / (tau² + phi·v1/n),
  where v1 is the sampling variance one serve carries and phi is the noise
  inflation implied by the observed split-half correlation. Quoting the binomial
  number alone would understate the requirement roughly fourfold.
- **Dispersion** is chi-square over degrees of freedom on per-match counts, with
  conditioned versions that expect each match at the player's rate against that
  returner's handedness, or their rate that calendar year. What a conditioner
  removes is the share of the movement it explains.
- **Drift** compares the early-vs-late profile distance to the median distance
  over 50 shuffled orderings of the same matches, so match-to-match restlessness
  is absorbed by the null and only the time ordering is on trial.
- **Break points** are compared to the player's own normal-point rate per side,
  then pooled at the break-point side mix. Without that adjustment most of the
  apparent pressure effect is which court the point was played in.
- **Windowing** is scored by multinomial log-loss per held-out serve, a proper
  scoring rule, so the holdout's own noise adds the same constant to every rule
  and cannot tilt the ranking. The picturable T-share column has that constant
  subtracted out. A decay rule has no clean denominator, so what ships with it is
  Kish's effective sample size, `(Σwn)² / Σw²n` — the number a coverage gate has
  to be applied to, not the raw serve count.
- No scipy in this project, so the chi-square tail is a Wilson-Hilferty normal
  approximation and multiplicity is handled with Benjamini-Hochberg at q = 0.10.

## Limits

- The notation records a target, not a serve: no speed, no spin, no returner
  position. "Wide" pools a kick and a flat slice out wide.
- Break points are selected — they arrive against good returners and when the
  server is already in trouble — so a shift on them is not purely a choice made
  under pressure.
- Steps 3 and 5 compare across matches and inherit the charter fingerprint;
  step 6 does not, since both buckets come from the same matches.
- Double faults are not separated out of the second-serve mix; a missed second
  serve still carries its target.
