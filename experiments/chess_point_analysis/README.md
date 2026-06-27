# Chess-style analysis of tennis points

A self-contained spike: can techniques used to analyze **chess games** be ported to
analyze individual **tennis points**? A point's shot notation (e.g. `4b37y1r3n#`)
is a tokenized, alternating-turn sequence ending in a terminal result — structurally
the same kind of object as a chess PGN move list. Nothing else in the repo decodes
these strings; this is the first point-level analysis here.

This spike builds **one** chess technique end-to-end — **shot quality / "blunder"
detection** (the centipawn-loss / accuracy idea) — which requires an empirical
**win-probability "engine eval"** underneath it. Other crossovers are catalogued in
[`CROSSOVER_IDEAS.md`](CROSSOVER_IDEAS.md) for later.

## The chess → tennis mapping built here

| Chess | Implemented as |
|---|---|
| PGN move list | `parser.py` — decode a point string into structured strokes |
| Engine eval (win-prob for a position) | `winprob.py` — empirical `P(server wins \| rally state)` |
| Opening explorer (next move + win% from a position) | `winprob.py` `explore_state()` |
| Centipawn loss / blunder (`?`,`??`) / accuracy % | `quality.py` — per-stroke WPA, marks, decision-quality score |
| Annotated game | `quality.py` `render_point()` |

## Files

- `parser.py` — pure decoder: point string → strokes (`hitter`, `side`, `direction`,
  `depth`, …) + `rally_len`, `outcome`, `server_won`. Notation per the Match Charting
  Project codebook; the point ending attaches to the last stroke (`*` winner, `#`
  forced, `@` unforced), strokes alternate from the server.
- `winprob.py` — `WinProbModel`: a frequency-table value function with parent-shrinkage
  smoothing (rare states back off to coarser ones, like an opening explorer). Exposes
  `position_value`, `base`, `shot_wpa`, `explore_state`.
- `quality.py` — WPA → annotation marks, annotated-point renderer, and per-player
  decision quality (`avg_wpa_lost`, an `accuracy` 0–100 rescale, forced/unforced split).
- `validate_parser.py` — cross-checks parsed aggregates against the project's own
  `stats_overview` totals (aces, DFs, winners, unforced; the repo's validation reference).
- `run.py` — end-to-end: fit the eval per gender, emit figures + a findings report.

## Run

```bash
uv run python experiments/chess_point_analysis/validate_parser.py 1500   # parser ✔ vs charted stats
uv run python experiments/chess_point_analysis/run.py                    # eval + quality + report
```

`run.py` writes `reports/chess_point_quality.md` and `reports/figures/chess_*.png`.

## What it shows (current results)

- **Parser is faithful.** Against `stats_overview`: aces 0.1% error (100% exact),
  double faults 0.8%, unforced 0.2% (97% exact), forehand/backhand winner & error
  splits within 1–5%. (The winners *total* carries a ~5% residual: upstream keeps
  volley/overhead winners out of the wing columns.)
- **The eval is sensible and calibrated.** Base `P(server wins)` lands at 72%/51%
  (men 1st/2nd serve) and 64%/46% (women) — realistic hold dynamics; serve-location
  eval ranks wide > T > body. Predicted win-prob tracks actual server-win rate on the
  diagonal (0.2–0.85), and per-point WPA telescopes exactly to `result − pre-serve value`.
- **The richer state earns its keep.** Beyond direction, the state reads return
  depth, slice-vs-drive, and net/approach — and each shows a real marginal signal:
  deep returns drop the server to 47% (vs 58% on shallow), a slice return leaves the
  server at 71% (vs 60% off a drive), and approaching the net lifts the server to 68%.
  Adding them widened the calibrated range without distorting it.
- **Decision quality has face validity.** Ranking by win-probability conceded per
  stroke puts consistent counterpunchers up top (Bautista Agut, Hewitt, Ferrer;
  Sorribes Tormo, Wozniacki, Radwanska) and high-variance shotmakers at the bottom
  (Cressy, Opelka; Ostapenko, Galfi).

## Honest limitations

- **No oracle for the "best" stroke.** Unlike a chess engine, negative WPA blends shot
  *selection*, *execution*, and the *pressure* the opponent applied. The forced/unforced
  split (`unforced_lost_share`) partly isolates self-inflicted losses, but the
  decision-quality score still measures *consistency / style* as much as *skill*.
- **Still a coarse state.** The eval reads the last stroke (wing, drive/slice/net
  kind, direction, net-approach, depth) plus capped ply — well-populated and now much
  more resolving, but it ignores the game/set score and flattens very long rallies
  (the oscillating eval late in the annotated point). Score-aware eval is in the backlog.
- **Charting bias.** Win rates inherit the same coverage skew the repo documents
  (later rounds over-charted); treat cross-player numbers as indicative, not official.

If the parser + eval prove useful, they're the natural pieces to graduate into
`src/match_charting_project/analysis/`.
