# Class-aware eval vs. style-blind eval

Does telling the win-probability eval *who* is playing — each player's style archetype
from the `player_styles` experiment — make it predict server-win better than the
style-blind eval already does? Built to answer that before investing in class-relative
WPA, because the extra complexity might not pay.

## Design (a fair A/B)

One model, one knob. `ClassAwareModel` subclasses the existing `WinProbModel` and
changes **only** the state features: with `use_class=False` it *is* the style-blind eval;
with `use_class=True` it inserts `(server_class, returner_class)` into the same shrinkage
backoff. This guarantees the baseline is byte-identical and any difference is purely the
class features. We test both natural insertions:

- **coarse** — matchup as a global conditioner (right after `sip, ply, to_hit`).
- **fine** — matchup only refines the full rally state (most-specific level).

Trained on identical match-split points (no point leakage), scored on the same held-out
positions. Primary metric: held-out log-loss; train log-loss is reported to expose
overfitting. Per gender. Run:

```bash
uv run python experiments/class_aware_eval/run.py     # needs reports/player_style_clusters.csv
```

This is a documented negative result, so `run.py` prints the comparison to stdout and
writes **no** report or figures — the conclusion below is the deliverable.

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
generalize **worse** on held-out data — the textbook overfitting signature, and it shows
up regardless of where the class features go. Two reasons it fails:

1. **Weak marginal signal.** Server-win% is nearly flat across the real archetypes
   (men 64–66%, women 57–60%); only the low-data `?` bucket sags. A server's *style*
   barely changes how *often* they hold — styles differ in the *texture* of points.
2. **Already captured.** That texture (slice, net, depth, direction, rally length) is
   exactly what the rich rally state encodes, so explicit class labels are redundant.

## Implication for class-relative WPA

Keep **one style-blind eval** as the shared currency. Put class-awareness in the
**benchmark**, not the model: compute each player's WPA against the single eval, then
compare them to their *archetype's* average. This isolates skill-within-style without the
incoherence of switching evals mid-point and without the overfitting shown here.
