# Chess → tennis crossover ideas (backlog)

Other ways chess-analysis techniques could map onto individual tennis points, beyond
the win-probability eval + shot-quality work already built in this directory. Each
builds on the same foundation: a point string is a tokenized, alternating-turn move
list (see `parser.py`). Kept here so the ideas aren't lost; none are built yet.

## Already built (for context)
- **Engine eval** → empirical `P(server wins | rally state)` (`winprob.py`).
- **Opening explorer** → `explore_state()` (next-stroke distribution + win% from a state).
- **Centipawn loss / blunder / accuracy** → per-stroke WPA, decision-quality score (`quality.py`).
- **Annotated game** → `render_point()`.

## Backlog

### 1. Shot-sequence language model  *(chess: neural/n-gram models on PGN)*
The ~30-token shot alphabet is tiny — perfect for an n-gram or small Markov model over
strokes. Payoffs:
- **Next-stroke prediction** and a **perplexity** score = how *predictable* a player is
  (low perplexity = patterned; high = varied). A creativity/variety fingerprint.
- **Surprise mining**: rallies whose stroke sequence is low-probability under the base
  model = unusual/creative points worth surfacing.
- **Rally generation**: sample synthetic but realistic points; sanity-check the eval.

### 2. Player style fingerprint  *(chess: opening repertoire / style classification)*
Vectorize each player by their stroke-pattern distribution (serve locations, slice%,
net-approach%, inside-out FH%, rally-length profile, FH/BH balance) and **cluster** into
styles (server-volleyer, baseline grinder, aggressive ball-striker, counterpuncher).
The decision-quality leaderboard already hints the consistency↔risk axis falls out
naturally; this would make the whole style space explicit.

### 3. Tactical motif mining  *(chess: forks, pins, recurring motifs)*
Detect recurring high-value stroke patterns via n-gram / regex over point strings:
serve+1 inside-out forehand, serve-and-volley, the wrong-foot, the ad-court kick to the
backhand. For each motif: frequency and success rate per player — a catalog of a
player's "tactics" and how well they work.

### 4. Finishing "tablebase"  *(chess: endgame tablebases)*
For terminal 1–2 stroke situations there's enough data to give near-*exact* empirical
win probabilities — e.g. "at net, opponent passing from the deuce corner" → put-away
rate. A lookup table of finishing situations, the small-piece tablebase analogue.

### 5. Point phases  *(chess: opening / middlegame / endgame)*
Treat serve+return / baseline rally / net finish as the three phases, each with its own
heuristics and success rates. Analyze transition behavior (who comes forward, when) and
phase-specific quality, rather than one number per point.

### 6. Score-aware eval  *(chess: nothing — tennis-specific extension)*
Fold the game/set score into the eval (the rally state currently ignores it). A point at
30–40 is worth more than at 40–0; combining rally-state WPA with the classic score-based
win-probability model would give a true "leverage-weighted" shot-quality metric.

## Honest differences to respect (why tennis ≠ chess)
- **Stochastic & partially observable.** Transitions are probabilistic and the state is
  coarse (fatigue, exact court position lost). Evals are inherently empirical/probabilistic,
  never "solved."
- **Short unit, huge n.** A point is ~1–10 strokes but there are ~1.85M of them — the
  opposite regime from chess. Favors frequency methods over deep search.
- **Soft "legal moves."** Any stroke is possible (with varying probability); no move
  generator is needed — the data *is* the realistic distribution.
- **No ground-truth engine.** There is no oracle for the best stroke, so "blunder" /
  "accuracy" conflate selection, execution, and opponent pressure. Always caveat.
- **Charting bias.** Win rates inherit the coverage skew the repo documents (later rounds
  over-charted). Report sample sizes; treat cross-player numbers as indicative.
