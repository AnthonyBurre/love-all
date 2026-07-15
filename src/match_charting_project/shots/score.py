"""Derive the service side (deuce vs ad court) from the game score.

The point strings never record which side a serve was struck to, but it is
fully determined by the score: the number of points already completed in the
current game (or tiebreak) fixes the side. Every game and every tiebreak opens
on the deuce court, then the side alternates with each point, so

    side = deuce if (points already played) is even, else ad.

The count of points already played is the sum of the two score tokens under the
right reading of the tokens:

- Regular game (and advantage-set long games): tokens are 0/15/30/40/AD, mapped
  to 0/1/2/3/4. The sum stays correct past deuce — 40-40 -> 6 (deuce court),
  AD-40 -> 7 (ad court).
- Tiebreak: tokens are integer point counts (e.g. ``3-2``); sum them directly.
  Point one (``0-0``) is served to the deuce court, then sides alternate, so
  the same parity rule is exact.

This keys off the *token type* (game token vs integer) rather than a separate
tiebreak detector, which is both simpler and correct for advantage-set games
that are still scored 15/30/40 at 6-6 or beyond (the data has ~9k such points;
there a score like ``15-0`` is a normal game, not a tiebreak). The rule is
orientation-independent — it uses only the sum — so server-first vs
returner-first scoring does not matter. ``0-0`` is the one score both readings
share, and both give 0 (deuce), so the overlap is harmless.
"""

DEUCE, AD, NA = "deuce", "ad", "na"

# Game-token -> points completed. Shared reading with the score-aware eval's
# ``_PT`` (``experiments/score_aware_eval/model.py``); keep the two in step.
_PT = {"0": 0, "15": 1, "30": 2, "40": 3, "AD": 4}


def serve_side(pts: "str | None") -> str:
    """Deuce/ad court for a point, from its (game or tiebreak) score string.

    Returns ``"deuce"``, ``"ad"``, or ``"na"`` when ``pts`` is missing or not a
    two-token score. Needs only ``pts`` — not games or a tiebreak flag — because
    both game and tiebreak scoring alternate side with the point count.
    """
    if not pts or "-" not in pts:
        return NA
    toks = pts.split("-")
    if len(toks) != 2:
        return NA
    a, b = toks
    if a in _PT and b in _PT:                 # 0/15/30/40/AD game tokens
        played = _PT[a] + _PT[b]
    elif a.isdigit() and b.isdigit():         # integer tiebreak counts
        played = int(a) + int(b)
    else:
        return NA
    return DEUCE if played % 2 == 0 else AD
