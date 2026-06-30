"""Does conditioning the eval on the match score actually help it predict points?

Run:  python experiments/score_aware_eval/run.py

Fits several evals on identical match-split training points, per gender:
  - score-blind         (the existing pure point-dynamics eval)
  - pressure (coarse)   break/game-point/deuce/tiebreak as a global conditioner
  - pressure (fine)     same tag, but only refining the full rally state
  - pressure+lead       also folds in the games/sets margin (richer -> overfit risk)
then scores them on the same held-out positions, with train-vs-test log-loss to
expose overfitting. Also prints the marginal server-win% by score bucket — the
clutch/momentum diagnostic. Prints to stdout; writes nothing (see README).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402

from compare import eval_model, paired_predictions, server_win_by  # noqa: E402
from model import ScoreAwareModel, in_test, load_points  # noqa: E402
from match_charting_project.analysis.coverage import connect  # noqa: E402

SAMPLE = 500_000
TRAIN_EVAL_CAP = 60_000  # cap points used for the (diagnostic) train-loss
GLABEL = {"M": "Men", "W": "Women"}
PRESSURE_ORDER = ["normal", "deuce", "game_pt", "break_pt", "tiebreak"]
LEAD_ORDER = ["set_behind", "behind", "even", "ahead", "set_ahead"]


def main() -> None:
    con = connect(read_only=True)
    best = -1e9

    for g in ("M", "W"):
        pts = load_points(con, g, sample=SAMPLE)
        train = [p for p in pts if not in_test(p.match_id)]
        test = [p for p in pts if in_test(p.match_id)]
        models = {
            "score-blind": ScoreAwareModel(use_score=False).fit(train),
            "pressure-coarse": ScoreAwareModel(score_pos="coarse",
                                               components=("pressure",)).fit(train),
            "pressure-fine": ScoreAwareModel(score_pos="fine",
                                             components=("pressure",)).fit(train),
            "pressure+lead": ScoreAwareModel(score_pos="coarse",
                                             components=("pressure", "lead")).fit(train),
        }
        base = eval_model(models["score-blind"], test)
        pa, pb, _ = paired_predictions(models["score-blind"], models["pressure-coarse"], test)

        print(f"\n=== {GLABEL[g]} — {base['n']:,} held-out positions "
              f"({len(test):,} points) ===")
        print(f"{'eval':<18}{'train LL':>10}{'test LL':>10}{'Δ vs blind':>12}{'Brier':>9}")
        for name, m in models.items():
            tr = eval_model(m, train, cap=TRAIN_EVAL_CAP)["log_loss"]
            te = eval_model(m, test)
            d = 100 * (base["log_loss"] - te["log_loss"]) / base["log_loss"]
            if name != "score-blind":
                best = max(best, d)
            print(f"{name:<18}{tr:>10.4f}{te['log_loss']:>10.4f}{d:>+11.2f}%{te['brier']:>9.4f}")
        print(f"predictions move by mean |Δ| = {np.abs(pb - pa).mean():.4f} (pressure-coarse vs blind)")

        wp = server_win_by(test, "pressure")
        print("server-win% by pressure:  ",
              " · ".join(f"{k}:{wp[k][0]:.1%} (n={wp[k][1]:,})"
                         for k in PRESSURE_ORDER if k in wp))
        wl = server_win_by(test, "lead")
        print("server-win% by match lead:",
              " · ".join(f"{k}:{wl[k][0]:.1%}" for k in LEAD_ORDER if k in wl))
    con.close()

    print(f"\nVERDICT: best score-aware change to held-out log-loss = {best:+.2f}% "
          f"-> {'helped' if best > 0.1 else 'did NOT help (keep the score-blind eval)'}.")


if __name__ == "__main__":
    main()
