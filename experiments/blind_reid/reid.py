"""Blind re-identification: does a performance vector point back at its author?

Two scores, both computed on players the metric never saw:

**Verification AUC** — over pairs of performances, the probability that a randomly
chosen *same-player* pair sits closer together than a randomly chosen *different-player*
pair. 0.5 is chance, 1.0 is a perfect fingerprint. Preferred as the headline because it
needs no baseline correction and survives pair filtering, which is what the controls do.

**Rank-1 accuracy** — for each performance, is its nearest neighbour the same player?
Reported against its own chance rate, which is *not* 1/n_players: it depends on how many
other performances each player has, so it is computed per query and averaged.

The metric matters as much as the features. Raw z-scored Euclidean distance treats a
feature that swings wildly between one player's own matches (unforced-error rate) as
equal evidence to one that barely moves (serve-direction lean). So we whiten by the
**pooled within-player covariance**: directions along which a single player varies from
match to match get shrunk, directions that separate players get stretched. This is the
speaker-verification trick (within-class covariance normalization), and it is the reason
the split below is non-negotiable — the covariance is fit on one set of players and
scored on a disjoint set, so a performance is never identified by a metric that was
shown that player's own scatter.
"""

import numpy as np

# Ridge on the within-class covariance, on the standardized scale. Sw is estimated
# from a few thousand pairs across ~30 dimensions, so a little shrinkage toward the
# identity keeps small-eigenvalue directions from being blown up into pure noise.
RIDGE = 0.25


def _pairs_of(labels: np.ndarray) -> "dict[object, np.ndarray]":
    idx: dict = {}
    for i, lab in enumerate(labels):
        idx.setdefault(lab, []).append(i)
    return {k: np.asarray(v) for k, v in idx.items()}


def split_players(players: np.ndarray, seed: int = 0,
                  frac_fit: float = 0.5) -> "tuple[np.ndarray, np.ndarray]":
    """Split *players* (not performances) into fit / eval masks.

    Splitting on the player keeps every performance of a player on one side, so the
    metric cannot have learned that player's personal within-match scatter.
    """
    uniq = np.array(sorted(set(players)))
    rng = np.random.default_rng(seed)
    rng.shuffle(uniq)
    fit_names = set(uniq[: int(round(frac_fit * len(uniq)))])
    fit = np.array([p in fit_names for p in players])
    return fit, ~fit


def fit_metric(X: np.ndarray, players: np.ndarray, ridge: float = RIDGE) -> dict:
    """Standardize, then whiten by pooled within-player covariance.

    Only players with >= 2 performances contribute to the within-class covariance
    (a single performance has no within-player scatter to measure).
    """
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd < 1e-9, 1.0, sd)
    Z = (X - mu) / sd

    d = Z.shape[1]
    Sw = np.zeros((d, d))
    n = 0
    for _, rows in _pairs_of(players).items():
        if len(rows) < 2:
            continue
        C = Z[rows] - Z[rows].mean(0)
        Sw += C.T @ C
        n += len(rows) - 1
    Sw = Sw / max(n, 1) if n else np.eye(d)
    Sw = (1 - ridge) * Sw + ridge * np.eye(d)

    # W = Sw^{-1/2}: distances in the transformed space are Mahalanobis w.r.t. Sw.
    w, V = np.linalg.eigh(Sw)
    w = np.maximum(w, 1e-6)
    W = V @ np.diag(w ** -0.5) @ V.T
    return {"mu": mu, "sd": sd, "W": W}


def apply_metric(X: np.ndarray, m: dict) -> np.ndarray:
    return ((X - m["mu"]) / m["sd"]) @ m["W"]


def distances(Y: np.ndarray) -> np.ndarray:
    """Full pairwise Euclidean distance matrix (n is a few thousand — fits fine)."""
    sq = (Y * Y).sum(1)
    D2 = sq[:, None] + sq[None, :] - 2 * (Y @ Y.T)
    np.fill_diagonal(D2, 0.0)
    return np.sqrt(np.maximum(D2, 0.0))


def auc(same: np.ndarray, diff: np.ndarray) -> float:
    """P(same-player distance < different-player distance), ties counted as half.

    Rank-based (Mann-Whitney), so it is exact rather than sampled, and cheap enough
    to recompute for every control subset.
    """
    if len(same) == 0 or len(diff) == 0:
        return float("nan")
    allv = np.concatenate([same, diff])
    order = allv.argsort(kind="mergesort")
    ranks = np.empty(len(allv), float)
    ranks[order] = np.arange(1, len(allv) + 1)
    # average ranks within ties
    srt = allv[order]
    i = 0
    while i < len(srt):
        j = i
        while j + 1 < len(srt) and srt[j + 1] == srt[i]:
            j += 1
        if j > i:
            ranks[order[i:j + 1]] = (i + j + 2) / 2
        i = j + 1
    r_same = ranks[: len(same)].sum()
    u = r_same - len(same) * (len(same) + 1) / 2
    # smaller distance = same-player, so AUC is 1 - (U / mn)
    return 1.0 - u / (len(same) * len(diff))


def pair_index(players: np.ndarray, meta: "dict[str, np.ndarray]",
               max_diff: "int | None" = 4_000_000, seed: int = 0) -> dict:
    """The pair list every score is computed over — built once, reused for every block.

    Flattens the upper triangle into parallel arrays: the two row indices, whether the
    pair is the same player, and one boolean per control axis, so a control is a mask
    over one fixed pair list rather than a separate pass. Different-player pairs are
    subsampled when there are too many; same-player pairs are always kept in full
    (they are the scarce side, and the sampling is what the AUC's precision rests on).

    Carries no distances — feed it to :func:`pair_dists` per feature set.
    """
    n = len(players)
    iu, ju = np.triu_indices(n, k=1)
    same_all = players[iu] == players[ju]

    rng = np.random.default_rng(seed)
    keep = same_all.copy()
    diff_idx = np.flatnonzero(~same_all)
    if max_diff is not None and len(diff_idx) > max_diff:
        diff_idx = rng.choice(diff_idx, max_diff, replace=False)
    keep[diff_idx] = True
    i, j = iu[keep], ju[keep]

    yr = meta["year"].astype(float)
    return {
        "i": i, "j": j,
        "same": players[i] == players[j],
        "diff_charter": meta["charted_by"][i] != meta["charted_by"][j],
        "diff_opponent": meta["opponent"][i] != meta["opponent"][j],
        "diff_surface": meta["surface"][i] != meta["surface"][j],
        "same_hand": (meta["hand"][i] == meta["hand"][j]) & (meta["hand"][i] != "?"),
        "year_gap": np.abs(yr[i] - yr[j]),
        "diff_match": meta["match_id"][i] != meta["match_id"][j],
    }


def pair_dists(Y: np.ndarray, pairs: dict) -> np.ndarray:
    """Distances for just the listed pairs (no full n x n matrix)."""
    diff = Y[pairs["i"]] - Y[pairs["j"]]
    return np.sqrt((diff * diff).sum(axis=1)) if diff.ndim > 1 else np.abs(diff)


def relabel(pairs: dict, labels: np.ndarray) -> dict:
    """Same pair list, different ``same`` definition — for the charter/null probes."""
    out = dict(pairs)
    out["same"] = labels[pairs["i"]] == labels[pairs["j"]]
    return out


def auc_on(pairs: dict, dist: np.ndarray,
           mask: "np.ndarray | None" = None) -> "tuple[float, int, int]":
    """AUC restricted to a pair subset; returns (auc, n_same, n_diff)."""
    m = np.ones(len(dist), bool) if mask is None else mask
    # A performance never pairs with its own match's opposite slot: the two share the
    # rally, so their "similarity" is the match, not the player.
    m = m & pairs["diff_match"]
    s = dist[m & pairs["same"]]
    d = dist[m & ~pairs["same"]]
    return auc(s, d), len(s), len(d)


def rank1(D: np.ndarray, players: np.ndarray,
          match_ids: np.ndarray) -> "tuple[float, float, int]":
    """Rank-1 accuracy and its per-query chance rate.

    A query's own performance and the opposite slot of its own match are excluded from
    the gallery; queries whose player has no other performance are skipped.
    """
    n = len(players)
    hits = 0
    chance = 0.0
    used = 0
    for i in range(n):
        ok = (np.arange(n) != i) & (match_ids != match_ids[i])
        if not ok.any():
            continue
        same = (players == players[i]) & ok
        if not same.any():
            continue                      # nothing to find; not a fair query
        d = np.where(ok, D[i], np.inf)
        hits += bool(players[int(d.argmin())] == players[i])
        chance += same.sum() / ok.sum()
        used += 1
    if not used:
        return float("nan"), float("nan"), 0
    return hits / used, chance / used, used


def self_vs_other(D: np.ndarray, players: np.ndarray,
                  match_ids: np.ndarray, min_perf: int = 4) -> "list[dict]":
    """Per-player: own spread vs distance to the field — the "am I my own nearest
    kind?" question, plus the closest *other* player to their centre.

    ``median_self`` is the median distance among a player's own performance pairs;
    ``median_other`` the median distance to every other player's performances. A
    player whose ``median_self`` exceeds ``median_other`` is, on this metric, less like
    themselves than like the average opponent — the case the experiment set out to find.
    """
    rows = []
    by = _pairs_of(players)
    for player, rows_i in by.items():
        if len(rows_i) < min_perf:
            continue
        sub = D[np.ix_(rows_i, rows_i)]
        mids = match_ids[rows_i]
        ok = mids[:, None] != mids[None, :]
        iu, ju = np.triu_indices(len(rows_i), k=1)
        selfd = sub[iu, ju][ok[iu, ju]]
        if len(selfd) < 3:
            continue
        others = np.setdiff1d(np.arange(len(players)), rows_i, assume_unique=False)
        od = D[np.ix_(rows_i, others)]
        # drop the opponent-in-the-same-match cells: shared rally, not shared style
        od = od[mids[:, None] != match_ids[others][None, :]]
        # nearest other player, by median distance from this player's performances
        nearest, nd = None, np.inf
        for other, orows in by.items():
            if other == player or len(orows) < 2:
                continue
            m = float(np.median(D[np.ix_(rows_i, orows)]))
            if m < nd:
                nearest, nd = other, m
        rows.append({
            "player": player, "n_perf": len(rows_i),
            "median_self": float(np.median(selfd)),
            "median_other": float(np.median(od)),
            "nearest_player": nearest, "nearest_dist": nd,
        })
    return rows


def confusable_pairs(D: np.ndarray, players: np.ndarray, match_ids: np.ndarray,
                     min_perf: int = 4, top: int = 12) -> "list[dict]":
    """Cross-player pairs closer than *each* player's own median self-distance.

    The concrete identity crossings: two different humans whose performances sit closer
    to each other than either sits to their own other showings.

    The bar is the **smaller** of the two self-distances, deliberately. Taking the
    larger would let a single erratic player — one whose own performances are scattered
    — pair "confusably" with half the tour, which says nothing about mutual similarity.
    Requiring the cross-distance to beat both self-distances makes the claim symmetric.
    """
    stats = {r["player"]: r for r in self_vs_other(D, players, match_ids, min_perf)}
    by = _pairs_of(players)
    out = []
    names = sorted(stats)
    for a_i, a in enumerate(names):
        for b in names[a_i + 1:]:
            sub = D[np.ix_(by[a], by[b])]
            ok = match_ids[by[a]][:, None] != match_ids[by[b]][None, :]
            if not ok.any():
                continue
            m = float(np.median(sub[ok]))
            bar = min(stats[a]["median_self"], stats[b]["median_self"])
            if m < bar:
                out.append({"a": a, "b": b, "cross": m,
                            "self_a": stats[a]["median_self"],
                            "self_b": stats[b]["median_self"],
                            "margin": bar - m})
    out.sort(key=lambda r: -r["margin"])
    return out[:top]
