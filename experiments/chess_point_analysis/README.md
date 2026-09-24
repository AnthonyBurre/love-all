# Chess-style analysis of tennis points

Can techniques for analyzing **chess games** be ported to individual **tennis
points**? A point's shot notation (e.g. `4b37y1r3n#`) is an alternating-turn sequence
ending in a result, the same kind of object as a chess PGN move list.

This builds **one** chess technique end to end, **shot quality / "blunder" detection**
(the centipawn-loss / accuracy idea), on top of an empirical **win-probability "engine
eval"**. Other crossovers are catalogued in
[`CROSSOVER_IDEAS.md`](CROSSOVER_IDEAS.md) for later.

## The chess → tennis mapping built here

All of these live in the library (`match_charting_project.shots`):

| Chess | Implemented as |
|---|---|
| PGN move list | `shots.notation` — decode a point string into structured strokes |
| Engine eval (win-prob for a position) | `shots.winprob` — empirical `P(server wins \| rally state)` |
| Opening explorer (next move + win% from a position) | `shots.winprob` `explore_state()` |
| Centipawn loss / blunder (`?`,`??`) / accuracy % | `shots.quality` — per-stroke WPA, marks, decision-quality score |
| Annotated game | `shots.quality` `render_point()` |

## Files

- `match_charting_project.shots.notation` — the decoder (parser, `stroke_kind`,
  `iter_parsed_points`, `point_features`) with a `points_parsed` materialize step
  (`match-charting-project shots`) and tests in `tests/test_notation.py`.
- `match_charting_project.shots.winprob` — `WinProbModel`, a frequency-table value
  function with parent-shrinkage smoothing (rare states back off to coarser ones, like
  an opening explorer). State reads wing, drive/slice/net kind, direction, net-approach,
  and return depth. Exposes `position_value`, `base`, `shot_wpa`, `explore_state`. Tests
  in `tests/test_winprob.py`.
- `match_charting_project.shots.quality` — WPA → annotation marks, annotated-point
  renderer, and per-player decision quality (`avg_wpa_lost`, an `accuracy` 0–100
  rescale, forced/unforced split). The port works, but the leaderboard doesn't mean what
  the chess original means. WPA telescopes within a point, so a per-stroke average is
  (concession per point) / (strokes per point), and rally length drives it (see the
  caveat in that module and the measurements in `../class_relative_wpa`). Treat
  `avg_wpa_lost` as an input to a style-relative comparison, never as a standalone
  ranking.

This folder holds the demo driver, `run.py`: fit the eval per gender, write figures and
a findings report.

## Run

```bash
uv run pytest tests/test_notation.py                 # parser ✔ (incl. vs charted stats)
uv run python experiments/chess_point_analysis/run.py   # eval + quality + report
```

`run.py` writes `reports/chess_point_quality.md` and `reports/figures/chess_*.png`.

## What it shows

- **Parser is faithful.** Against `stats_overview`: aces 0.1% error (100% exact),
  double faults 0.8%, unforced 0.2% (97% exact), forehand/backhand winner & error
  splits within 1–5%. (The winners *total* carries a ~5% residual: upstream keeps
  volley/overhead winners out of the wing columns.)
- **The eval is sensible and calibrated.** Base `P(server wins)` lands at 72%/51%
  (men 1st/2nd serve) and 64%/46% (women), realistic hold rates; serve-location
  eval ranks wide > T > body. Predicted win-prob tracks actual server-win rate on the
  diagonal (0.2–0.85), and per-point WPA telescopes exactly to `result − pre-serve value`.
- **The richer state helps.** Beyond direction, the state reads return depth,
  slice vs drive, and net approach, and each has a real marginal signal:
  deep returns drop the server to 47% (vs 58% on shallow), a slice return leaves the
  server at 71% (vs 60% off a drive), and approaching the net lifts the server to 68%.
  Adding them widened the calibrated range without distorting it.
- **The decision-quality ranking is mostly rally length.** Ranking by win probability
  conceded per stroke puts consistent counterpunchers on top (Bautista Agut, Hewitt,
  Ferrer; Sorribes Tormo, Wozniacki, Radwanska) and high-variance shotmakers at the
  bottom (Cressy, Opelka; Ostapenko, Galfi). That looks plausible, but
  `../class_relative_wpa` shows it tracks rally length, not skill.

## Limitations

- **No oracle for the "best" stroke.** Unlike a chess engine, negative WPA blends shot
  *selection*, *execution*, and the *pressure* the opponent applied. The forced/unforced
  split (`unforced_lost_share`) partly isolates self-inflicted losses, but the
  decision-quality score still measures *consistency / style* as much as *skill*.
- **Still a coarse state.** The eval reads the last stroke (wing, drive/slice/net
  kind, direction, net approach, depth) plus capped ply. It ignores the game and set
  score and flattens very long rallies (the oscillating eval late in the annotated
  point). A score-aware variant in `../score_aware_eval` did **not** improve it,
  consistent with the Klaassen–Magnus point-independence result.
- **Charting bias.** Win rates inherit the same coverage skew the repo documents
  (later rounds over-charted); treat cross-player numbers as indicative, not official.
