"""Row-shape repair: what `repair_matches` rebuilds, what it drops, and what it refuses
to guess at.

This runs before anything is coerced or derived, so it is the first thing that sees a
crowdsourced row and the last chance to tell a damaged one from a real one. Every failure
here is silent by construction: a row that has slipped a column still has a value in every
cell, and every one of those values is the right *type*. A per-column check reads it as
several unrelated oddities — an unusual surface, a best-of of 1 — and passes it through.

The two shapes it answers for:

* a *short* row, where `Player 1` and `Player 2` are absent rather than empty, so the hand
  codes sit in the player columns and everything after them is one or two places to the
  left. A bare "R" in the player column is the tell; nobody is called R.
* a row missing only `Surface`, which reads as an ordinary match until you notice the
  surface is an umpire's name.

The repair is deliberately narrow, and the narrowness is the part worth pinning: only the
five fields the match_id encodes plus the two self-validating hands are restored, and
everything from `time` on is nulled rather than slid back. A uniform shift assumes the row
is missing exactly the columns you think it is, and the one row in the corpus that needs
rebuilding is missing three, not two — shifted uniformly it comes out with an umpire in the
surface column and every value plausible enough to survive a per-column check.
"""

import pandas as pd

from match_charting_project.ingest import validate
from matchframes import INTACT, SHIFTED
from matchframes import frame as _frame


def test_a_shifted_row_with_an_intact_twin_is_dropped():
    """Most of them arrive twice. The shifted copy is a partial duplicate of a row we
    already have whole, so dropping it costs nothing."""
    df, rep = validate.repair_matches(_frame(INTACT, SHIFTED))
    assert len(df) == 1
    assert df.iloc[0]["player1"] == "Ann Alpha"
    assert df.iloc[0]["surface"] == "Grass"          # the intact row is untouched
    assert rep["shifted_rows"] == 1
    assert rep["dropped_duplicate"] == [SHIFTED["match_id"]]
    assert rep["repaired"] == []


def test_a_lone_shifted_row_is_rebuilt_from_its_match_id():
    """The match_id is the one field still known to be in the right place, and it encodes
    five of the columns that moved."""
    df, rep = validate.repair_matches(_frame(SHIFTED))
    assert len(df) == 1
    row = df.iloc[0]
    assert (row["player1"], row["player2"]) == ("Ann Alpha", "Bea Beta")
    assert (row["date"], row["tournament"], row["round"]) == ("20260601", "Wimbledon", "F")
    assert rep["repaired"] == [SHIFTED["match_id"]]
    assert rep["dropped_duplicate"] == []


def test_the_hands_are_recovered_only_when_they_look_like_hands():
    """A hand cell holds R, L, U or nothing, so a wrong one cannot masquerade as a right
    one — which is what makes these two safe to move back when the rest is not."""
    df, _ = validate.repair_matches(_frame(SHIFTED))
    assert (df.iloc[0]["player1_hand"], df.iloc[0]["player2_hand"]) == ("R", "L")

    # A second player column holding something that is not a hand code contributes no
    # hand rather than a guessed one. (player1 still holds one, which is what marks the
    # row as shifted in the first place.)
    odd = {**SHIFTED, "player2": ""}
    df, _ = validate.repair_matches(_frame(odd))
    assert df.iloc[0]["player1_hand"] == "R"
    assert pd.isna(df.iloc[0]["player2_hand"])


def test_a_rebuilt_rows_tail_is_nulled_and_not_slid_back():
    """The repair this file exists to prevent. Shifting the tail uniformly assumes the row
    is missing exactly two columns; the one that needs rebuilding is missing three, and
    comes out with the umpire in the surface column. Null says "unknown", which is true."""
    df, _ = validate.repair_matches(_frame(SHIFTED))
    row = df.iloc[0]
    for col in ("time", "court", "surface", "umpire", "best_of", "final_tb", "charted_by"):
        assert pd.isna(row[col]), col
    # In particular, nothing in the row now claims a surface nobody has played on.
    assert row["surface"] != "Eva Asderaki-Moore"


def test_an_ambiguous_match_id_is_dropped_rather_than_guessed():
    """`rest` is Tournament-Round-Player_1-Player_2, so it splits into exactly four. A
    hyphenated surname makes five, and there is no way to tell from the string which hyphen
    is a separator. Guessing is how you invent a player."""
    ambiguous = {**SHIFTED,
                 "match_id": "20260601-M-Wimbledon-F-Felix_Auger-Aliassime-Bea_Beta"}
    df, rep = validate.repair_matches(_frame(ambiguous))
    assert df.empty
    assert rep["dropped_unrecoverable"] == [ambiguous["match_id"]]
    assert rep["repaired"] == []


def test_a_row_that_is_only_missing_its_surface_has_its_tail_nulled():
    """The damage the front-shift check cannot see: all the players are present, so nothing
    marks the row, and best-of reads as 1 — which is not decorative, it feeds the win
    probability."""
    no_surface = {**INTACT,
                  "match_id": "20260602-M-Wimbledon-SF-Cara_Gamma-Dana_Delta",
                  "player1": "Cara Gamma", "player2": "Dana Delta",
                  "surface": "Eva Asderaki-Moore", "umpire": "5", "best_of": "1"}
    df, rep = validate.repair_matches(_frame(INTACT, no_surface))
    bad = df[df["match_id"] == no_surface["match_id"]].iloc[0]
    for col in ("surface", "umpire", "best_of", "final_tb", "charted_by"):
        assert pd.isna(bad[col]), col
    # The players and the date are still where they belong, so the row stays a match.
    assert (bad["player1"], bad["player2"]) == ("Cara Gamma", "Dana Delta")
    assert bad["date"] == "20260601"
    assert rep["tail_nulled"] == [no_surface["match_id"]]
    # The sound row keeps its surface: this names rows, it does not clear a column.
    assert df[df["match_id"] == INTACT["match_id"]].iloc[0]["surface"] == "Grass"


def test_an_intact_frame_is_left_alone():
    df, rep = validate.repair_matches(_frame(INTACT))
    assert len(df) == 1 and df.iloc[0]["surface"] == "Grass"
    assert rep["shifted_rows"] == 0
    assert rep["repaired"] == rep["dropped_duplicate"] == rep["dropped_unrecoverable"] == []
    assert rep["tail_nulled"] == []
