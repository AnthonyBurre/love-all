"""Tests for the projections that ship to the site's insights DB.

Two projections here have real failure modes, and both fail *quietly* — the build
succeeds and the panel renders, just with the wrong picture.

The serve-placement CSV carries both a career mix and a recency-weighted one under
similar names, so a build that renames one onto the other's column ships duplicate
columns with the wrong values winning; both are plausible percentages, so nothing
looks wrong. These tests pin which number lands in which column, and that the
reliability gate the experiment computes survives the trip.

The pattern projection joins two experiments into one table, and the return family
carries three columns the rally family has no meaning for. Blanks in those columns
make pandas infer a float dtype, which turns serve direction "6" into "6.0" —
matching none of the renderer's cases, so the serve silently vanishes from every
court drawing. These tests pin the codes as text and the two families as disjoint.
"""

import pandas as pd
import pytest

from match_charting_project.site import build_insights

# One player, both sides: career mix deliberately far from the recent mix so a
# mix-up cannot pass. Only the columns _serve_placement reads are included.
ROWS = [
    {"player": "A Player", "gender": "M", "side": "deuce", "serve": "1st", "n": 9000,
     "wide": 0.30, "t": 0.60, "recent_wide": 0.55, "recent_t": 0.35,
     "recent_n_eff": 1200.0, "recent_years": "2024-2026", "reliable": 1,
     "drift_ratio": 2.5},
    {"player": "A Player", "gender": "M", "side": "ad", "serve": "1st", "n": 8000,
     "wide": 0.40, "t": 0.50, "recent_wide": 0.62, "recent_t": 0.28,
     "recent_n_eff": 1100.0, "recent_years": "2024-2026", "reliable": 0,
     "drift_ratio": 2.5},
    # Second serves and rows with no recent window are not part of the projection.
    {"player": "A Player", "gender": "M", "side": "deuce", "serve": "2nd", "n": 3000,
     "wide": 0.20, "t": 0.40, "recent_wide": 0.25, "recent_t": 0.45,
     "recent_n_eff": 400.0, "recent_years": "2024-2026", "reliable": 1,
     "drift_ratio": 2.5},
    {"player": "B Player", "gender": "W", "side": "deuce", "serve": "1st", "n": 400,
     "wide": 0.44, "t": 0.46, "recent_wide": None, "recent_t": None,
     "recent_n_eff": None, "recent_years": "", "reliable": None,
     "drift_ratio": None},
]
META = [{"gender": "M", "rule": "decay", "rule_param": 10, "recent_matches": 34,
         "n80_wide": 864, "n80_t": 1175, "n80_pay": 11315, "noise_inflation": 3.74,
         "tour_deuce_wide": 0.4427, "tour_deuce_t": 0.4611,
         "tour_ad_wide": 0.5103, "tour_ad_t": 0.4001}]


@pytest.fixture
def reports(tmp_path, monkeypatch):
    monkeypatch.setattr(build_insights, "REPORTS", tmp_path)
    return tmp_path


def _write(reports, rows=ROWS, meta=META):
    pd.DataFrame(rows).to_csv(reports / "serve_tendencies_players.csv", index=False)
    if meta is not None:
        pd.DataFrame(meta).to_csv(reports / "serve_tendencies_meta.csv", index=False)


def test_ships_the_recent_mix_not_the_career_one(reports):
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    deuce = serve[serve.side == "deuce"].iloc[0]
    assert deuce.wide == pytest.approx(0.55)      # recent, not the 0.30 career value
    assert deuce.t == pytest.approx(0.35)
    assert deuce.career_wide == pytest.approx(0.30)
    assert deuce.career_t == pytest.approx(0.60)
    assert deuce.career_n == 9000


def test_no_duplicate_columns(reports):
    """The renaming bug this file exists for: duplicate labels reach DuckDB as
    ``wide`` and ``wide_1``, and the panel reads whichever came first."""
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    assert len(set(serve.columns)) == len(serve.columns)


def test_only_first_serves_with_a_recent_window(reports):
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    assert len(serve) == 2                        # both sides of the 1st-serve rows
    assert set(serve.player) == {"A Player"}      # B Player has no recent window


def test_reliability_gate_survives_as_an_int(reports):
    _write(reports)
    serve, _meta = build_insights._serve_placement()
    by_side = serve.set_index("side")
    assert by_side.loc["deuce", "reliable"] == 1
    assert by_side.loc["ad", "reliable"] == 0
    assert by_side["reliable"].dtype.kind == "i"
    assert by_side["n_eff"].dtype.kind == "i"


def test_meta_rows_are_prefixed_and_numeric(reports):
    _write(reports)
    _serve, meta = build_insights._serve_placement()
    keys = {r["key"]: r["value"] for r in meta}
    assert keys["serve_n80_wide_M"] == 864
    assert keys["serve_tour_ad_t_M"] == pytest.approx(0.4001)
    assert all(isinstance(r["value"], float) for r in meta)


def test_missing_csv_is_not_an_error(reports):
    """The experiment may not have been run; the site drops the section instead."""
    serve, meta = build_insights._serve_placement()
    assert serve is None and meta == []


def test_missing_meta_still_ships_the_table(reports):
    _write(reports, meta=None)
    serve, meta = build_insights._serve_placement()
    assert len(serve) == 2 and meta == []


# --- pattern families ------------------------------------------------------------------
# court_response owns the rally family; serve_plus_one owns the return family and adds
# tier/serve_side/serve_dir to it. Minimal rows: only the columns _patterns reads.
CR_ROWS = [
    {"player": "A Player", "gender": "M", "family": "rally", "state": "drive into the middle",
     "response": "crosscourt FH drive", "state_depth": "",
     "state_kind": "drive", "resp_kind": "drive", "inc_code": 2, "resp_code": 1,
     "lift": 1.8, "count": 40, "n_state": 300, "evidence": 33.9,
     "win_rate": 0.55, "tour_win_rate": 0.51,
     "field_share": 0.22, "state_win_rate": 0.48},
    {"player": "A Player", "gender": "M", "family": "ret", "state": "mid-depth drive return",
     "response": "crosscourt FH drive", "state_depth": "mid-depth",
     "state_kind": "drive", "resp_kind": "drive", "inc_code": 2, "resp_code": 1,
     "lift": 1.7, "count": 30, "n_state": 200, "evidence": 23.0,
     "win_rate": 0.57, "tour_win_rate": 0.52,
     "field_share": 0.19, "state_win_rate": 0.45},
]
SP_ROWS = [
    {"player": "A Player", "gender": "M", "family": "ret", "tier": "full",
     "state": "deuce court, T serve · mid-depth drive return", "response": "crosscourt FH drive",
     "serve_side": "deuce", "serve_dir": 6, "state_depth": "mid-depth",
     "state_kind": "drive", "resp_kind": "drive",
     "inc_code": 2, "resp_code": 1, "lift": 2.0, "count": 90, "n_state": 400, "evidence": 90.0,
     "win_rate": 0.58, "tour_win_rate": 0.56,
     "field_share": 0.27, "state_win_rate": 0.50},
    {"player": "B Player", "gender": "W", "family": "ret", "tier": "pooled",
     "state": "mid-depth drive return", "response": "BH net shot down the line",
     "serve_side": "", "serve_dir": "", "state_depth": "mid-depth",
     "state_kind": "drive", "resp_kind": "net",
     "inc_code": 3, "resp_code": 1, "lift": 1.5, "count": 20, "n_state": 150, "evidence": 11.7,
     "win_rate": 0.49, "tour_win_rate": 0.47,
     "field_share": 0.14, "state_win_rate": 0.41},
]


def _write_patterns(reports, sp=SP_ROWS):
    pd.DataFrame(CR_ROWS).to_csv(reports / "court_response_players.csv", index=False)
    if sp is not None:
        pd.DataFrame(sp).to_csv(reports / "serve_plus_one_players.csv", index=False)


def test_return_family_comes_from_serve_plus_one(reports):
    """Both experiments compute a ret family; only one of them may ship, or the panel
    describes one shot twice under two different conditionings."""
    _write_patterns(reports)
    p = build_insights._patterns()
    ret = p[p.family == "ret"]
    assert len(ret) == 2                                  # serve_plus_one's, not the CSV's 1
    assert set(ret.tier) == {"full", "pooled"}
    assert "mid-depth drive return" == ret[ret.tier == "pooled"].iloc[0].state
    assert len(p[p.family == "rally"]) == 1               # court_response's, untouched


def test_serve_dir_survives_as_text_not_a_float(reports):
    """The quiet one: a blank in the column infers float64, "6" becomes "6.0", and the
    renderer's dir === "6" test fails, so the serve disappears from the drawing."""
    _write_patterns(reports)
    p = build_insights._patterns()
    full = p[p.tier == "full"].iloc[0]
    assert full.serve_dir == "6"
    for col in ("inc_code", "resp_code", "serve_dir", "serve_side", "tier"):
        assert p[col].map(type).eq(str).all(), col


def test_stroke_kinds_reach_the_panel(reports):
    """The drawing branches on them: a volley is met in the air, so a response the panel
    cannot tell from a drive gets a bounce drawn under a ball that never landed."""
    _write_patterns(reports)
    p = build_insights._patterns()
    assert set(p.state_kind) == {"drive"} and set(p.resp_kind) == {"drive", "net"}
    for col in ("state_kind", "resp_kind"):
        assert p[col].map(type).eq(str).all(), col


def test_rally_rows_carry_blanks_not_nan(reports):
    """The rally family has no side. Those cells reach the panel as text either way, so
    a NaN would print the string "nan" in a card."""
    _write_patterns(reports)
    rally = build_insights._patterns().query("family == 'rally'").iloc[0]
    assert (rally.tier, rally.serve_side, rally.serve_dir) == ("", "", "")


def test_falls_back_to_court_response_when_serve_plus_one_is_missing(reports):
    """A stale checkout should ship the pooled return rows, not an empty section."""
    _write_patterns(reports, sp=None)
    p = build_insights._patterns()
    ret = p[p.family == "ret"]
    assert len(ret) == 1 and set(ret.tier) == {"pooled"}
    assert (ret.iloc[0].serve_side, ret.iloc[0].serve_dir) == ("", "")


# --- hold and break rates ---------------------------------------------------------------
# The panel's two ring marks are derived from raw points, and every way of getting the
# derivation wrong produces a plausible percentage rather than an error. Attributing a game
# to the returner swaps a hold rate for a break rate — 80% and 20% are both real numbers a
# server could post. Reading the first point of a game instead of the last scores the game
# for whoever won the opening rally. Counting tiebreaks as service games credits half of
# every one of them to a player who did not serve it.
#
# One synthetic match with a known answer, built as points: three service games for player 1
# (two held, one broken), two for player 2 (one held, one broken), and a tiebreak that must
# not be counted for either.
def _points_db(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "t.duckdb"))
    con.execute("CREATE TABLE matches (match_id VARCHAR, gender VARCHAR, "
                "player1 VARCHAR, player2 VARCHAR)")
    con.execute("INSERT INTO matches VALUES ('m1', 'M', 'A Player', 'B Player')")
    con.execute("CREATE TABLE points (match_id VARCHAR, pt BIGINT, game_num VARCHAR, "
                "gm1 BIGINT, gm2 BIGINT, svr BIGINT, pt_winner BIGINT)")
    rows, pt = [], 0

    def game(gn, gm1, gm2, svr, winner, opener=None):
        """Four points: the opener may go either way, the last one decides the game."""
        nonlocal pt
        for i in range(4):
            pt += 1
            w = (opener if i == 0 and opener else winner)
            rows.append(("m1", pt, str(gn), gm1, gm2, svr, w))

    #  gn  score  server  game won by   first point won by
    game(1, 0, 0, 1, 1)
    game(2, 1, 0, 2, 1)                 # player 1 breaks
    game(3, 1, 1, 1, 1, opener=2)       # held, but the opening point went the other way
    game(4, 2, 1, 2, 2)
    game(5, 2, 2, 1, 2)                 # player 2 breaks
    # A tiebreak: both players serve inside it, and it sits at 6-6.
    for i, (svr, w) in enumerate([(1, 1), (2, 2), (2, 1), (1, 1)]):
        pt += 1
        rows.append(("m1", pt, "13", 6, 6, svr, w))
    con.executemany("INSERT INTO points VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return con


def test_hold_and_break_are_scored_for_the_right_player(tmp_path, monkeypatch):
    monkeypatch.setattr(build_insights, "MIN_GAMES", 1)
    g = build_insights._game_rates(_points_db(tmp_path)).set_index("player")
    # Player 1 served games 1, 3 and 5 and held two of them; player 2 served 2 and 4 and
    # held one. Break rates are the same games read from the other side. The rates ship
    # rounded to four places, which is the tolerance here.
    assert g.loc["A Player", "hold_rate"] == pytest.approx(2 / 3, abs=5e-5)
    assert g.loc["B Player", "hold_rate"] == pytest.approx(1 / 2, abs=5e-5)
    assert g.loc["A Player", "break_rate"] == pytest.approx(1 / 2, abs=5e-5)
    assert g.loc["B Player", "break_rate"] == pytest.approx(1 / 3, abs=5e-5)


def test_tiebreaks_are_not_service_games(tmp_path, monkeypatch):
    monkeypatch.setattr(build_insights, "MIN_GAMES", 1)
    g = build_insights._game_rates(_points_db(tmp_path)).set_index("player")
    assert g.loc["A Player", "serve_games"] == 3
    assert g.loc["B Player", "serve_games"] == 2
    assert g.loc["A Player", "return_games"] == 2


def test_a_game_goes_to_whoever_won_its_last_point(tmp_path, monkeypatch):
    """Game 3 opens with a point to the returner and still ends as a hold."""
    monkeypatch.setattr(build_insights, "MIN_GAMES", 1)
    g = build_insights._game_rates(_points_db(tmp_path)).set_index("player")
    assert g.loc["A Player", "hold_rate"] == pytest.approx(2 / 3, abs=5e-5)


def test_thin_players_come_through_null_rather_than_wrong(tmp_path, monkeypatch):
    """Below the floor there is no rate, so the ring draws without its mark."""
    monkeypatch.setattr(build_insights, "MIN_GAMES", 100)
    assert build_insights._game_rates(_points_db(tmp_path)).empty


# --- return winners ---------------------------------------------------------------------
# The return ring's outright-win core, and the same class of quiet failure as the game rates
# above: crediting the server instead of the returner turns a returner's best shot into a
# serve statistic, and dropping the rally-length guard counts every winner the player ever hit
# as one struck off the return. Both produce a percentage rather than an error.
def _parsed_db(tmp_path):
    import duckdb
    con = duckdb.connect(str(tmp_path / "p.duckdb"))
    con.execute("CREATE TABLE matches (match_id VARCHAR, gender VARCHAR, "
                "player1 VARCHAR, player2 VARCHAR)")
    con.execute("INSERT INTO matches VALUES ('m1', 'W', 'A Player', 'B Player')")
    con.execute("CREATE TABLE points (match_id VARCHAR, pt BIGINT, svr BIGINT, pt_winner BIGINT)")
    con.execute("CREATE TABLE points_parsed (match_id VARCHAR, pt BIGINT, rally_len BIGINT, "
                "outcome VARCHAR, server_won BOOLEAN, parse_ok BOOLEAN)")
    #    svr  rally  outcome           server_won   what it is
    rows = [
        (1, 2, "winner", False),        # a return winner for B
        (1, 2, "winner", False),        # another
        (1, 2, "unforced_error", True),  # B nets the return: not a winner
        (1, 4, "winner", False),        # B wins, but four shots in: a rally winner
        (1, 1, "ace", True),            # an ace: never reaches the return
        (2, 2, "winner", False),        # a return winner for A
        (2, 6, "winner", False),        # A wins a rally
        (2, 2, "forced_error", True),   # A pushed into a return error
    ]
    for i, (svr, rl, outcome, sw) in enumerate(rows, 1):
        con.execute("INSERT INTO points VALUES ('m1', ?, ?, ?)",
                    [i, svr, svr if sw else (3 - svr)])
        con.execute("INSERT INTO points_parsed VALUES ('m1', ?, ?, ?, ?, TRUE)",
                    [i, rl, outcome, sw])
    return con


def test_return_winners_are_credited_to_the_returner(tmp_path, monkeypatch):
    monkeypatch.setattr(build_insights, "MIN_RETURN_PTS", 1)
    r = build_insights._return_winners(_parsed_db(tmp_path)).set_index("player")
    # B returned the five points A served and struck two winners off the return; A returned
    # the three points B served and struck one.
    assert r.loc["B Player", "ret_winner_rate"] == pytest.approx(2 / 5, abs=5e-5)
    assert r.loc["A Player", "ret_winner_rate"] == pytest.approx(1 / 3, abs=5e-5)


def test_only_winners_struck_on_the_return_count(tmp_path, monkeypatch):
    """A winner four shots into the rally is not a return winner, and neither is an ace."""
    monkeypatch.setattr(build_insights, "MIN_RETURN_PTS", 1)
    r = build_insights._return_winners(_parsed_db(tmp_path)).set_index("player")
    # B won three of the five points they returned; only two of those came off the return.
    assert r.loc["B Player", "ret_winner_rate"] < 3 / 5


def test_return_winners_respect_their_own_floor(tmp_path, monkeypatch):
    """Below the floor there is no rate, so the arc draws in one colour and the line is absent."""
    monkeypatch.setattr(build_insights, "MIN_RETURN_PTS", 100)
    assert build_insights._return_winners(_parsed_db(tmp_path)).empty
