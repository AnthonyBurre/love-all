"""The screening statistics behind the pattern cards.

Three experiments screen thousands of candidate patterns per player and keep the ones that
beat a baseline, so what these two functions do decides what the site prints as a finding.
Both fail quietly: a wrong tail is still a number in [0, 1] that sorts, and a wrong
correction still shrinks a list.

`binom_tail` is not the textbook sum. That one is exact and fine on a handful of
pre-filtered candidates, but `comb` on a few thousand strokes is an integer far too large to
convert to a float, so it overflows on the full screen. This walks outward from the mode
instead, where the largest term cannot underflow and each neighbour follows from the last by
a ratio. Its docstring claims agreement with the exact sum to about 1e-12 — this file is
what checks that claim, on the small `n` where the exact sum can still be computed.
"""

from math import comb, isfinite

import pytest

from match_charting_project.stats import bh, binom_tail, holm


def _exact(k: int, n: int, p: float) -> float:
    """P(X >= k) summed directly. Correct for small n, and unusable for large."""
    return sum(comb(n, j) * p ** j * (1 - p) ** (n - j) for j in range(k, n + 1))


@pytest.mark.parametrize("n", [1, 2, 5, 20, 60, 150])
@pytest.mark.parametrize("p", [0.01, 0.1, 0.35, 0.5, 0.72, 0.99])
def test_agrees_with_the_exact_sum(n, p):
    """The docstring's claim, over every k, at the sizes where both can be computed."""
    for k in range(0, n + 2):
        assert binom_tail(k, n, p) == pytest.approx(_exact(k, n, p), abs=1e-12)


def test_the_degenerate_baselines():
    """A baseline of 0 or 1 is not a screening question, but it reaches here from a context
    nobody ever won or lost, and must not divide by zero."""
    assert binom_tail(0, 10, 0.0) == 1.0
    assert binom_tail(1, 10, 0.0) == 0.0        # cannot happen at all
    assert binom_tail(3, 10, 1.0) == 1.0        # certain
    assert binom_tail(0, 10, 0.5) == 1.0        # P(X >= 0) is always 1
    assert binom_tail(11, 10, 0.5) == 0.0       # more successes than trials


def test_a_screen_sized_n_stays_finite_and_ordered():
    """The case the direct sum cannot do: `comb(4000, 2000)` has over 1,200 digits and
    raises on the conversion to float. The walk has to stay inside double range and stay
    monotone, because the screen ranks on this."""
    n, p = 4000, 0.37
    vals = [binom_tail(k, n, p) for k in range(1300, 1701, 50)]
    assert all(isfinite(v) and 0.0 <= v <= 1.0 for v in vals)
    assert vals == sorted(vals, reverse=True)   # P(X >= k) falls as k rises
    # And the tail well out in the tail is small but not flattened to zero — those are
    # exactly the patterns a screen most wants to rank.
    assert 0.0 < binom_tail(1900, n, p) < 1e-20


def test_the_tail_at_the_mode_is_about_a_half():
    """A coarse sanity anchor that does not depend on the walk's internals: at the mean of
    a symmetric binomial, half the mass is at or above it."""
    assert binom_tail(50, 100, 0.5) == pytest.approx(0.5, abs=0.05)


# --- the false-discovery correction ------------------------------------------------------

PVALS = [0.001, 0.008, 0.039, 0.041, 0.042, 0.6, 0.9]


def test_bh_returns_in_input_order():
    """The caller zips these back against the candidates they came from, so a sorted return
    would attach every p-value to the wrong pattern."""
    shuffled = [0.6, 0.001, 0.9, 0.039]
    adj = bh(shuffled)
    assert len(adj) == len(shuffled)
    # The smallest input keeps the smallest adjustment, wherever it sat.
    assert adj.index(min(adj)) == shuffled.index(min(shuffled))


def test_bh_is_monotone_and_never_below_the_raw_p_value():
    adj = bh(PVALS)
    assert all(a >= p for a, p in zip(adj, PVALS))          # a correction only ever inflates
    assert all(a <= 1.0 for a in adj)
    # Step-up: sorting by the raw value must leave the adjusted values non-decreasing, or
    # a stricter candidate would rank below a looser one.
    by_raw = [a for _p, a in sorted(zip(PVALS, adj))]
    assert by_raw == sorted(by_raw)


def test_bh_on_an_empty_family():
    """A player with no candidate contexts at all — the loop must not divide by zero."""
    assert bh([]) == []


def test_bh_keeps_more_than_holm_at_a_screens_family_size():
    """The reason these screens use one and not the other, at the size where it matters.

    The two agree on a handful of candidates and diverge over a family of hundreds, which
    is what a per-player screen actually produces: Holm controls the chance of *any* false
    positive and leaves almost nothing, where BH controls the share of the shown set that is
    spurious — the claim the panel actually makes.
    """
    # Five real effects buried in 195 nulls spread across the rest of the range.
    family = [0.00002, 0.0001, 0.0004, 0.0008, 0.001]
    family += [0.05 + 0.95 * i / 195 for i in range(195)]
    b, h = bh(family), holm(family)
    assert all(x <= y for x, y in zip(b, h))            # BH is never the stricter of the two
    assert sum(x < 0.05 for x in b) == 5                # all five effects survive
    assert sum(y < 0.05 for y in h) < 5                 # Holm loses some of them
