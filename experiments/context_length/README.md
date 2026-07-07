# Context length: how much shot history does charted data support?

Two site features hard-code a sequence length nobody ever tested. **Signature
sequences** (`shot_language`) are bigrams — one incoming shot, one response.
**Shot-making triggers** (`shot_triggers`) condition on exactly two prior
shots. Longer contexts are strictly more specific ("serve wide → short slice →
FH drive to 3" is a real tactic; "FH drive to 3" is a shot), but every added
token multiplies sparsity by the ~35-token alphabet. This experiment finds
where the tradeoff actually lands, with three tests that don't care about
anyone's intuition:

1. **Held-out information** (triggers) — split every player's strokes by match
   into two halves; train per-context attempt tables on one half, predict the
   other with a shrinkage backoff chain (context of K shots backs off to K−1,
   … down to the player's base rate, then the tour's). If adding a third shot
   of history carries real signal, held-out log-loss drops at K=3; if it's
   noise, the backoff flattens and the gain is ~0. All models are scored on
   the *same strokes* (those with three prior shots), so the comparison is
   apples to apples.
2. **Stability** — would the displayed lists replicate? For triggers: the
   correlation between a context's attempt rate in one half of a player's
   charted matches and the same context's rate in the other half, per K. For
   signatures: compute each player's top-5 highest-lift patterns independently
   in each half and measure the overlap (Jaccard) of the two lists, at bigram
   and trigram length.
3. **Display coverage** — at the production thresholds (60 strokes per
   context, 12 attempts, lift ≥ 1.5 / 25 occurrences per signature), how many
   qualifying patterns and covered players survive at each length.

## Honest limitations

- The split is by match (hash), not time, so "stability" means sampling
  stability, not stability of a player's tactics across their career — era
  drift makes real lists slightly less stable than measured here.
- The backoff evaluation predicts *attempts* (the shot-making decision).
  Conversion tables are ~5× sparser; if attempts don't support K=3, conversion
  certainly doesn't.
- Sequence length interacts with the token alphabet (~35 symbols). A coarser
  alphabet could afford longer contexts; that's a different experiment.

Run: `python experiments/context_length/run.py` →
`reports/context_length.md` + `reports/figures/context_length.png`.
