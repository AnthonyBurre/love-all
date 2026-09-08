"""Match rows in the shape `build_matches` reads them, shared by the ingest tests.

One intact row and the same match as it arrives damaged. Both `test_validate_repair` (what
the repair does to them) and `test_ingest_build` (that the steps still compose in order)
work from these, so the two cannot drift into describing different damage.
"""

import pandas as pd

from match_charting_project.ingest import validate

# A sound row, written out in MATCH_COLS order so the damaged ones can be read against it.
INTACT = {
    "match_id": "20260601-M-Wimbledon-F-Ann_Alpha-Bea_Beta",
    "player1": "Ann Alpha", "player2": "Bea Beta",
    "player1_hand": "R", "player2_hand": "L",
    "date": "20260601", "tournament": "Wimbledon", "round": "F",
    "time": "1:30:00", "court": "Centre Court", "surface": "Grass",
    "umpire": "Eva Asderaki-Moore", "best_of": "5", "final_tb": "1",
    "charted_by": "someone",
}
# The same match as it arrives short: `Player 1` and `Player 2` are absent rather than
# empty, so the hand codes sit in the player columns and every later field is one or two
# places left of where it belongs. A bare "R" in the player column is the tell.
SHIFTED = {
    "match_id": "20260601-M-Wimbledon-F-Ann_Alpha-Bea_Beta",
    "player1": "R", "player2": "L",
    "player1_hand": "20260601", "player2_hand": "Wimbledon",
    "date": "F", "tournament": "1:30:00", "round": "Centre Court",
    "time": "Grass", "court": "Eva Asderaki-Moore", "surface": "5",
    "umpire": "1", "best_of": "someone", "final_tb": None,
    "charted_by": None,
}


def frame(*rows: dict) -> pd.DataFrame:
    """A matches frame in file order, as `build_matches` hands it over — every cell a
    string, and no `gender` column yet where a test does not need one."""
    return pd.DataFrame(list(rows), columns=validate.MATCH_COLS)
