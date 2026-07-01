"""Experiment-local DB helper. The score decoding + serve+return strength graduated to
``match_charting_project.winprob_match``; only the calibration-specific ground truth
(who actually won each charted match) lives here now.
"""


def eventual_winners(con) -> dict:
    """``match_id -> winning player (1 or 2)`` from the last charted point."""
    rows = con.execute(
        "SELECT match_id, last(pt_winner ORDER BY pt) AS winner, "
        "       max(set1) AS s1, max(set2) AS s2 "
        "FROM points WHERE pt_winner IN (1,2) GROUP BY match_id"
    ).fetchall()
    return {mid: winner for mid, winner, s1, s2 in rows if winner in (1, 2)}
