"""An order-2 Markov "language model" over the shot alphabet.

The chess analogue of an opening book / a move-prediction model: P(next shot |
the last couple of shots). Trained by counting, smoothed by linear interpolation
of trigram/bigram/unigram estimates so every continuation has nonzero probability
(needed for surprise / perplexity). The model is the *field* model — fit on
everyone — so a player's average surprise under it measures how far their shot
choices stray from tour norms (their unpredictability).
"""

import math
from collections import Counter, defaultdict

from tokens import END, START

# Interpolation weights for trigram / bigram / unigram (sum to 1).
L3, L2, L1 = 0.7, 0.2, 0.1


class NGramModel:
    def __init__(self):
        self.tri: dict = defaultdict(Counter)   # (t-2, t-1) -> Counter(next)
        self.bi: dict = defaultdict(Counter)    # (t-1,)     -> Counter(next)
        self.uni: Counter = Counter()           # next       -> count
        self.n = 0

    def add_point(self, toks: "list[str]") -> None:
        seq = [START, START, *toks, END]
        for i in range(2, len(seq)):
            a, b, t = seq[i - 2], seq[i - 1], seq[i]
            self.tri[(a, b)][t] += 1
            self.bi[(b,)][t] += 1
            self.uni[t] += 1
            self.n += 1

    def fit(self, sequences) -> "NGramModel":
        for toks in sequences:
            self.add_point(toks)
        return self

    @property
    def vocab(self) -> int:
        return len(self.uni)

    def _p_uni(self, t: str) -> float:
        return (self.uni[t] + 1) / (self.n + self.vocab)        # add-1, always > 0

    def prob(self, a: str, b: str, t: str) -> float:
        """Interpolated P(t | a, b); falls back through lower orders for rare context."""
        p1 = self._p_uni(t)
        cb = self.bi.get((b,))
        p2 = cb[t] / cb.total() if cb else p1
        ct = self.tri.get((a, b))
        p3 = ct[t] / ct.total() if ct else p2
        return L3 * p3 + L2 * p2 + L1 * p1

    def surprise(self, a: str, b: str, t: str) -> float:
        """−log2 P(t | a, b): bits of surprise for the actual next shot."""
        return -math.log2(self.prob(a, b, t))

    def point_surprises(self, toks: "list[str]") -> "list[float]":
        """Per-stroke surprise, aligned to ``toks`` (END excluded)."""
        seq = [START, START, *toks, END]
        return [self.surprise(seq[i - 2], seq[i - 1], seq[i])
                for i in range(2, len(seq) - 1)]   # one per real stroke

    def perplexity(self, sequences) -> float:
        bits, k = 0.0, 0
        for toks in sequences:
            seq = [START, START, *toks, END]
            for i in range(2, len(seq)):
                bits += self.surprise(seq[i - 2], seq[i - 1], seq[i])
                k += 1
        return 2 ** (bits / max(k, 1))
