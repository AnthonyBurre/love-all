"""Does conditioning the eval on player style classes actually help?

Run:  python experiments/class_aware_eval/run.py

This is a settled negative result (see README) — a class-aware eval overfits and does
not beat the style-blind eval. The script stays runnable to *reproduce* that, but it
writes no reports or figures (a failed experiment's value is its conclusion, which lives
in this folder's README). It prints the comparison to stdout.

Fits three evals on identical match-split training points, per gender:
  - style-blind        (the existing eval)
  - class-aware coarse (matchup as a global conditioner)
  - class-aware fine   (matchup only refines the full rally state)
then scores all three on the same held-out positions, with train-vs-test log-loss to
expose overfitting. Needs reports/player_style_clusters.csv (run player_styles first).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402

from compare import eval_model, paired_predictions, server_win_by_class  # noqa: E402
from model import ClassAwareModel, in_test, load_class_map, load_points  # noqa: E402
from match_charting_project.analysis.coverage import connect  # noqa: E402
from match_charting_project.paths import PROJECT_ROOT  # noqa: E402

SAMPLE = 500_000
TRAIN_EVAL_CAP = 60_000  # cap points used for the (diagnostic) train-loss
CLUSTERS = PROJECT_ROOT / "reports" / "player_style_clusters.csv"
GLABEL = {"M": "Men", "W": "Women"}


def main() -> None:
    if not CLUSTERS.exists():
        raise SystemExit("Missing reports/player_style_clusters.csv — run player_styles first.")
    class_map = load_class_map(CLUSTERS)
    con = connect(read_only=True)
    best = -1e9

    for g in ("M", "W"):
        pts = load_points(con, g, class_map, sample=SAMPLE)
        train = [p for p in pts if not in_test(p.match_id)]
        test = [p for p in pts if in_test(p.match_id)]
        models = {
            "style-blind": ClassAwareModel(use_class=False).fit(train),
            "class coarse": ClassAwareModel(use_class=True, class_pos="coarse").fit(train),
            "class fine": ClassAwareModel(use_class=True, class_pos="fine").fit(train),
        }
        base_ll = eval_model(models["style-blind"], test)["log_loss"]
        both = eval_model(models["style-blind"], test, both_classified_only=True)["n"]
        n_test = eval_model(models["style-blind"], test)["n"]
        pa, pb, _ = paired_predictions(models["style-blind"], models["class coarse"], test)

        print(f"\n=== {GLABEL[g]} — {n_test:,} held-out positions "
              f"({both / max(n_test, 1):.0%} both players classified) ===")
        print(f"{'eval':<14}{'train LL':>10}{'test LL':>10}{'Δ vs blind':>12}{'Brier':>9}")
        for name, m in models.items():
            tr = eval_model(m, train, cap=TRAIN_EVAL_CAP)["log_loss"]
            te = eval_model(m, test)
            d = 100 * (base_ll - te["log_loss"]) / base_ll
            if name != "style-blind":  # verdict is about the best class-aware variant
                best = max(best, d)
            print(f"{name:<14}{tr:>10.4f}{te['log_loss']:>10.4f}{d:>+11.2f}%{te['brier']:>9.4f}")
        print(f"predictions move by mean |Δ| = {np.abs(pb - pa).mean():.4f} (coarse vs blind)")
        win_by = server_win_by_class(test, "s_class")
        print("raw server-win% by server class:",
              " · ".join(f"{k}:{v[0]:.0%}" for k, v in sorted(win_by.items())))
    con.close()

    print(f"\nVERDICT: best class-aware change to held-out log-loss = {best:+.2f}% "
          f"-> {'helped' if best > 0.1 else 'did NOT help (keep the style-blind eval)'}.")


if __name__ == "__main__":
    main()
