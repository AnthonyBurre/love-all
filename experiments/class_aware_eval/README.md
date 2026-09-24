# Class-aware eval vs. style-blind eval

Does telling the win-probability eval *who* is playing (each player's style archetype
from `player_styles`) make it predict server-win better than the style-blind eval?

## Design

One model, one knob. `ClassAwareModel` subclasses the existing `WinProbModel` and
changes **only** the state features: with `use_class=False` it *is* the style-blind eval;
with `use_class=True` it inserts `(server_class, returner_class)` into the same shrinkage
backoff. The baseline is byte-identical, so any difference comes from the class features.
Two insertion points:

- **coarse** — matchup as a global conditioner (right after `sip, ply, to_hit`).
- **fine** — matchup only refines the full rally state (the most specific level).

Trained on identical match-split points (no point leakage), scored on the same held-out
positions. Primary metric: held-out log-loss; train log-loss is reported to expose
overfitting. Per gender. Run:

```bash
uv run python experiments/class_aware_eval/run.py     # needs reports/player_style_clusters.csv
```

This is a documented negative result, so `run.py` prints the comparison to stdout and
writes no report or figures; the conclusion below is the result.

## Result: it does not pay off

| eval | train LL | test LL | Δ test vs blind |
|---|---|---|---|
| style-blind (men) | 0.6737 | **0.6758** | — |
| class coarse (men) | 0.6676 | 0.6781 | −0.34% |
| class fine (men) | 0.6675 | 0.6766 | −0.12% |
| style-blind (women) | 0.6806 | **0.6833** | — |
| class coarse (women) | 0.6725 | 0.6863 | −0.43% |
| class fine (women) | 0.6725 | 0.6849 | −0.23% |

Both class-aware variants fit the **training** data better (train LL drops ~0.6–0.8%) but
do **worse** on held-out data: overfitting, wherever the class features go. Two reasons:

1. **Weak marginal signal.** Server-win% is nearly flat across the real archetypes
   (men 64–66%, women 57–60%); only the low-data `?` bucket sags. A server's *style*
   barely changes how *often* they hold; styles differ in how points are played.
2. **Already captured.** That (slice, net, depth, direction, rally length) is what the
   rally state encodes, so class labels are redundant.

## Implication

Keep **one style-blind eval**, and put class-awareness in the **benchmark** instead:
compute each player's WPA against the single eval, then compare it with what their style
predicts. That avoids switching evals mid-point and the overfitting shown here.
`../class_relative_wpa` builds that benchmark (and finds the metric itself is mostly
rally length).
