"""Cluster player fingerprints into style archetypes (numpy only, no new deps).

Standardize the feature vectors, pick k by silhouette, run k-means++ (with
restarts for stability), and describe each cluster by its most extreme standardized
features plus the players nearest its centroid. PCA is kept for a 2-D view.
"""

import numpy as np


def standardize(X: np.ndarray):
    mu = X.mean(0)
    sd = X.std(0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd, mu, sd


def pca(Z: np.ndarray, k: int = 2):
    """Top-k principal components of an already-standardized matrix."""
    Zc = Z - Z.mean(0)
    _, S, Vt = np.linalg.svd(Zc, full_matrices=False)
    comps = Vt[:k]
    scores = Zc @ comps.T
    explained = (S ** 2) / (S ** 2).sum()
    return scores, comps, explained[:k]


def _kpp_init(Z, k, rng):
    centers = [Z[rng.integers(len(Z))]]
    for _ in range(1, k):
        d2 = np.min([((Z - c) ** 2).sum(1) for c in centers], axis=0)
        centers.append(Z[rng.choice(len(Z), p=d2 / d2.sum())])
    return np.array(centers)


def kmeans(Z, k, restarts: int = 16, iters: int = 100, seed: int = 0):
    rng = np.random.default_rng(seed)
    best = None
    for _ in range(restarts):
        C = _kpp_init(Z, k, rng)
        lab = np.zeros(len(Z), dtype=int)
        for _ in range(iters):
            lab = ((Z[:, None, :] - C[None, :, :]) ** 2).sum(2).argmin(1)
            newC = np.array([Z[lab == j].mean(0) if (lab == j).any() else C[j]
                             for j in range(k)])
            if np.allclose(newC, C):
                break
            C = newC
        inertia = ((Z - C[lab]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, lab, C)
    return best[1], best[2], best[0]


def silhouette(Z, lab) -> float:
    D = np.sqrt(((Z[:, None, :] - Z[None, :, :]) ** 2).sum(2))
    labs = np.unique(lab)
    sil = np.zeros(len(Z))
    for i in range(len(Z)):
        same = lab == lab[i]
        same[i] = False
        a = D[i, same].mean() if same.any() else 0.0
        b = min(D[i, lab == j].mean() for j in labs if j != lab[i])
        sil[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(sil.mean())


def label_from_centroid(centroid, features, n: int = 3) -> str:
    """Short human label: the n strongest standardized features, with arrows."""
    order = np.argsort(-np.abs(centroid))[:n]
    return "  ".join(f"{'↑' if centroid[i] > 0 else '↓'}{features[i]}" for i in order)


def describe(df, Z, lab, features, n_exemplars: int = 6):
    """Per-cluster: size, defining (standardized) features, nearest-centroid players."""
    out = {}
    for j in sorted(set(lab)):
        mask = lab == j
        cen = Z[mask].mean(0)
        idx = np.where(mask)[0]
        nearest = idx[np.argsort(((Z[mask] - cen) ** 2).sum(1))[:n_exemplars]]
        out[int(j)] = {
            "size": int(mask.sum()),
            "label": label_from_centroid(cen, features),
            "centroid": cen,
            "top_features": [(features[i], float(cen[i]))
                             for i in np.argsort(-np.abs(cen))[:5]],
            "exemplars": [df.index[i] for i in nearest],
        }
    return out
