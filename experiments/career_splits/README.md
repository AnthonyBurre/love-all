# Career splitting: should long careers be split into eras?

A long career (Federer spans 24 charted years) is one "player" to every other analysis,
which hides real change. This folder is the **justification** for the optional
**`player_eras`** table
(built by `match-charting-project eras`; production logic lives in
`match_charting_project.analysis.career_eras`). It answers: **does cutting a long career
into eras yield different players, or just two noisier samples of the same one?**

## The test

Splitting can always be done (the data supports 2.3× more entities); the question is
whether a split is meaningful. For each long career:

- **chronological gap** — style distance between the early and late halves (by points), in
  standardized 10-feature style space, and
- **random-split noise** — the same distance for the career's points shuffled into two
  random halves (median over many shuffles; seeded per player, so it's deterministic).

If chronological ≫ random, the career evolved; if they're similar, the "eras" are
sampling noise. The distance between two *different* players is the reference point.

```bash
uv run python experiments/career_splits/run.py     # regenerate this report + figure
uv run match-charting-project eras                 # (re)build the player_eras table
```

`run.py` writes `reports/career_splits.md` + the figure (the evidence). The era *map*
itself is the `player_eras` DB table, not a file here.

## What it finds: split *selectively*, not across the board

- Among **long careers** (≥4000 pts and an ≥8-year span: 102 men, 59 women), the median
  early-vs-late gap is only **~1.3×** the random-split noise. Most players are
  **stable** across their careers, so a blanket split would mostly dilute data.
  (Relaxing the span gate to 5 charted years adds ~46 candidates but only 2 more
  splits.)
- A **minority changes clearly** (>1.5× noise): **34 players**. They match documented
  changes: **Sabalenka** fixing her serve yips (double-fault rate −1.3σ), **Benoit
  Paire's** late-career unravel (df +3.2σ), **Michael Chang** adding serve power (ace
  rate +1.2σ, more T serves), **Kim Clijsters'** two career phases either side of her
  comeback.
- A median era gap is ~45% of the distance to a *different player*, so eras are partly
  distinct.

**Verdict:** split only the evolved long careers, into early and late (the only contrast
the test validated). That takes the tracked set from **358 to 392**. The mapping is the
**`player_eras`** table (`player, gender, era, year_start, year_end, n_points, evolved,
entity`); the unevolved majority stay whole, and any analysis can join points to it on
`year BETWEEN year_start AND year_end`. The report's *threshold sensitivity* table shows
how the split count moves with the cutoff (e.g. a uniform 2.0 erases the women).

## Limitations

- **Style-mix resolution.** Evolution is measured in shot-mix features (serve location,
  slice/net, aggression, errors). A career change that doesn't move the *mix* (purely
  physical decline, or hitting the same shots better) is invisible here; this is the
  space the downstream clustering uses.
- **Charting coverage drifts over a career**, so some "change" is coverage, not the
  player; and sparse senior/exhibition matches can mis-date a career tail. Binary splits
  limit the damage; finer (3+) eras weren't validated.
- The 1.5× threshold is a judgement call; the figure shows the full distribution behind
  it.
