"""Held-out scoring to decide whether class-awareness earns its complexity.

Both models predict P(server wins) on the *same* non-terminal positions of the
*same* held-out points, so every comparison is paired. Lower log-loss / Brier is
better; we also measure how far the predictions actually move (if class barely
changes the eval, the complexity isn't buying anything).
"""

import numpy as np


def eval_model(model, points, both_classified_only: bool = False, cap: "int | None" = None):
    """Log-loss + Brier for one model over held-out non-terminal positions."""
    p, y = [], []
    for pt in (points[:cap] if cap else points):
        if both_classified_only and ("?" in (pt.s_class, pt.r_class)):
            continue
        label = 1.0 if pt.server_won else 0.0
        for j in range(1, len(pt.shots)):
            p.append(model.position_value(pt, j))
            y.append(label)
    p, y = np.array(p), np.array(y)
    return {"log_loss": log_loss(p, y), "brier": brier(p, y), "n": len(y)}


def paired_predictions(model_a, model_b, points, both_classified_only: bool = False):
    """Predictions from two models + the label, over held-out non-terminal positions."""
    pa, pb, y = [], [], []
    for pt in points:
        if both_classified_only and ("?" in (pt.s_class, pt.r_class)):
            continue
        label = 1.0 if pt.server_won else 0.0
        for j in range(1, len(pt.shots)):
            pa.append(model_a.position_value(pt, j))
            pb.append(model_b.position_value(pt, j))
            y.append(label)
    return np.array(pa), np.array(pb), np.array(y)


def log_loss(p, y, eps: float = 1e-6) -> float:
    p = np.clip(p, eps, 1 - eps)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y) -> float:
    return float(np.mean((p - y) ** 2))


def server_win_by_class(points, by: str = "s_class"):
    """Marginal server-win% by a class field — shows whether class carries signal."""
    acc = {}
    for pt in points:
        k = getattr(pt, by)
        a = acc.setdefault(k, [0, 0])
        a[0] += 1
        a[1] += 1 if pt.server_won else 0
    return {k: (v[1] / v[0], v[0]) for k, v in acc.items() if v[0] >= 200}
