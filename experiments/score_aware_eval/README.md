# Score-aware eval vs. pure point-dynamics eval

Does telling the win-probability eval *where in the match* a point sits — break
point, game/set lead, tiebreak — make it predict server-win better than the pure
point-dynamics eval already does? Or are points ~iid given the rally state and
serve number (the classic Klaassen–Magnus "points are nearly independent" result)?
This keeps the existing eval and adds a score-aware variant *next to* it to settle
the question before trusting either.

## Design (a fair A/B)

One model, one knob. `ScoreAwareModel` subclasses the existing `WinProbModel` and
changes **only** the state features: with `use_score=False` it *is* the
point-dynamics eval; with `use_score=True` it folds a compact match-score tag into
the same shrinkage backoff. So the baseline is byte-identical and any difference is
purely the score features. We test where the tag enters and how rich it is:

- **pressure (coarse)** — leverage bucket (`break_pt` / `game_pt` / `deuce` /
  `tiebreak` / `normal`) as a global conditioner, right after `sip, ply, to_hit`.
- **pressure (fine)** — same tag, but only refining the *full* rally state (the
  strictest "does it add anything?" test).
- **pressure + lead** — also folds in the games/sets margin (`set_ahead` …
  `set_behind`); richer, so the overfitting test.

The `pts` column is **server-first** — verified, not assumed: server-ahead states
(`40-0`, `AD-40`) dominate their mirror for *both* servers, which only holds if the
left token is the server's score. Games/sets are flipped to the server's
perspective via `svr`. Trained on identical match-split points (no point leakage),
scored on the same held-out positions; primary metric held-out log-loss, with train
log-loss reported to expose overfitting. Per gender. Run:

```bash
uv run python experiments/score_aware_eval/run.py
```

Like `class_aware_eval`, this is a documented negative result, so `run.py` prints
to stdout and writes **no** report or figures — the conclusion below is the
deliverable.

## Result: it does not pay off

| eval | train LL | test LL | Δ test vs blind |
|---|---|---|---|
| score-blind (men) | 0.6737 | **0.6758** | — |
| pressure-coarse (men) | 0.6728 | 0.6766 | −0.11% |
| pressure-fine (men) | 0.6726 | 0.6762 | −0.06% |
| pressure+lead (men) | 0.6690 | 0.6777 | −0.29% |
| score-blind (women) | 0.6806 | **0.6833** | — |
| pressure-coarse (women) | 0.6784 | 0.6843 | −0.15% |
| pressure-fine (women) | 0.6784 | 0.6839 | −0.08% |
| pressure+lead (women) | 0.6727 | 0.6856 | −0.33% |

Every score-aware variant fits the **training** data better (train LL drops, most of
all for the richer `pressure+lead`) yet generalizes **worse** on held-out points —
the textbook overfitting signature, worst for the richest score tag. Keep the
pure point-dynamics eval.

## The twist: the score effects are real — they're just *selection*

Unlike the class-aware experiment (where server-win% was flat across archetypes, so
there was nothing to find), here the marginal score effects are clearly **non-flat**:

**Server-win% by pressure** (held-out points)

| | normal | deuce | game pt | break pt | tiebreak |
|---|---|---|---|---|---|
| Men | 64.4% | 62.7% | 65.4% | **59.6%** | 64.6% |
| Women | 57.1% | 59.0% | 58.6% | **55.6%** | 58.8% |

**Server-win% by match lead**

| | set behind | behind | even | ahead | set ahead |
|---|---|---|---|---|---|
| Men | 60.9% | 60.0% | 64.7% | 66.7% | **67.1%** |
| Women | 54.1% | 54.4% | 57.2% | 62.2% | **60.4%** |

Break points sag ~5 pts and match lead climbs monotonically ~7 pts — both large and
intuitive. So why doesn't conditioning on them help? Because the correlation is
**selection, not exploitable signal**:

1. **Break points are reached, not random.** You are at 0–40 *because* the returner
   has already won this game's points — a tough service game (strong returner, off
   day, second serves). The low server-win% is mostly that selection, and the bit
   that's predictable is already in the rally state and serve number.
2. **The leader is the better player.** Players ahead in the match win more service
   points because they are *stronger*, not because the scoreboard makes them serve
   better. Without knowing *who* is playing, "ahead" is just a noisy proxy for
   quality — and folding it into the rally-state backoff fragments cells and
   overfits (hence `pressure+lead` is worst).
3. **Already captured.** Whatever score context predicts about *this* point's
   outcome, the rich rally state (serve number, depth, direction, slice/net, rally
   length) and the 1st/2nd-serve split already encode.

As a cross-check, the score-blind baseline reproduces the `class_aware_eval`
numbers exactly (men 0.6758, women 0.6833) — same eval, same split.

## Implication

Keep **one point-dynamics eval** as the shared currency; do not condition it on the
score. The score *does* matter — but for **leverage** (which points are worth more),
not for **point-win probability**. That belongs in a layer *on top of* the eval (a
game→set→match win-probability / leverage model that weights each shot's WPA by how
much its point swings the match), not inside it. The point eval should stay the
honest, score-blind "how is this rally going" engine that such a layer consumes.
