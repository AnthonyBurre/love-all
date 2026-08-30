"""Small statistical helpers shared by the pattern-mining experiments.

Three experiments — ``shot_triggers``, ``serve_plus_one`` and ``rally_patterns`` — screen
a large number of candidate patterns per player and keep the ones that beat a baseline.
That shape needs an exact binomial tail and a false-discovery correction, and it needs
both to mean the same thing in all three: a per-player Benjamini-Hochberg family in one
place and a fixed threshold in another is not a difference readers can see in the panel,
which prints the survivors side by side.

They lived in ``deep_patterns`` first — the experiment ``rally_patterns`` replaced — and
were copied nowhere, which is why the other two shipped uncorrected: the tool being in a
neighbouring directory is not the same as it being available.
"""

from math import exp, lgamma, log, log1p

__all__ = ["binom_tail", "bh", "holm"]


def binom_tail(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p), summed outward from the mode.

    The direct ``sum(comb(n, j) * p**j * (1-p)**(n-j))`` is exact and fine on a handful
    of pre-filtered candidates; called on every context that has a baseline it overflows,
    because ``comb`` on a few thousand strokes is an integer far too large to convert to
    a float. Walking out from the mode keeps every term inside double range — the largest
    term is ``pmf(mode)``, about ``1/sqrt(2*pi*n*p*q)``, which cannot underflow — and each
    neighbour follows from the one before by a ratio. Dividing by the mass actually
    accumulated makes the result insensitive to where the walks stop.

    Agrees with the exact sum to ~1e-12 across any p a screen would act on.
    """
    if p <= 0:
        return 0.0 if k > 0 else 1.0
    if p >= 1:
        return 1.0
    if k <= 0:
        return 1.0
    if k > n:
        return 0.0
    mode = min(n, max(0, int((n + 1) * p)))
    pm = exp(lgamma(n + 1) - lgamma(mode + 1) - lgamma(n - mode + 1)
             + mode * log(p) + (n - mode) * log1p(-p))
    r = p / (1.0 - p)
    total = pm
    tail = pm if mode >= k else 0.0

    # Both walks stop once the remaining mass cannot move either figure. The tail gets its
    # own test: cutting off when a term is negligible against `total` alone would flatten a
    # genuinely tiny tail to zero before its first term was ever reached, which is the
    # p-value of exactly the patterns a screen most wants to rank.
    def spent(term, tail):
        return term < total * 1e-18 and (tail > 0.0 and term < tail * 1e-16)

    term = pm
    for j in range(mode, n):                      # upward from the mode
        term *= (n - j) / (j + 1) * r
        total += term
        if j + 1 >= k:
            tail += term
        if spent(term, tail):
            break
    term = pm
    for j in range(mode, 0, -1):                  # downward from the mode
        term *= j / ((n - j + 1) * r)
        total += term
        if j - 1 >= k:
            tail += term
        if spent(term, tail):
            break
    return min(1.0, tail / total)


def bh(pvals: list) -> list:
    """Benjamini-Hochberg adjusted p-values (step-up), returned in the input order.

    The right correction for these screens rather than Holm: they are looking for a set of
    patterns worth showing, and controlling the share of that set which is spurious is the
    claim the panel actually makes. Holm controls the chance of *any* false positive, which
    at these family sizes would leave almost nothing.
    """
    m = len(pvals)
    if not m:
        return []
    order = sorted(range(m), key=lambda i: pvals[i], reverse=True)
    adj, running = [1.0] * m, 1.0
    for rank, i in enumerate(order):
        running = min(running, min(1.0, m / (m - rank) * pvals[i]))
        adj[i] = running
    return adj


def holm(pvals: list) -> list:
    """Holm step-down adjusted p-values, returned in the input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj, running = [1.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvals[i]))
        adj[i] = running
    return adj
