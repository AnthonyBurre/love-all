"""The Wikipedia feed readers: draw sheets, tour calendar, and the guard on both.

All offline — the wikitext samples below are trimmed from the real pages (Washington 2026
and the 2026 ATP Tour schedule), keeping the shapes that actually caused bugs: pipes nested
inside ``{{flagicon|X}}`` and ``[[Target|Display]]``, byes written by *omitting* a round-1
pair, disambiguated article titles, and multi-tag seed cells.
"""

from match_charting_project.live import espn, wiki

# A 4-slot half: two played pairs, then a bye (slots 01/02 absent, entrant in RD2-team01).
DRAW = """
==Draw==
{{Draw key}}
===Finals===
{{4TeamBracket-Tennis3|RD1=Semifinals|RD1-team1={{flagicon|AUS}} [[Alex de Minaur]]}}
===Top half===
{{16TeamBracket-Compact-Tennis3-Byes
|RD1=First round
|RD1-seed03=WC
|RD1-team03='''{{flagicon|GRE}} [[Stefanos Tsitsipas|S Tsitsipas]]'''
|RD1-seed04=Q
|RD1-team04={{flagicon|USA}} [[Marcos Giron|M Giron]]
|RD1-seed05=
|RD1-team05={{flagicon|USA}} [[Tommy Paul (tennis)|T Paul]]
|RD1-seed06=<small>2/WC</small>
|RD1-team06={{flagicon|USA}} [[Martin Damm (born 2003)|M Damm]]
|RD1-seed07=Alt/LL
|RD1-team07={{flagicon|AUS}} [[Cruz Hewitt|C Hewitt]]
|RD1-seed08=7
|RD1-team08={{flagicon|CZE}} [[Jakub Menšik|J Menšik]]
|RD2-seed01=1
|RD2-team01={{flagicon|AUS}} [[Alex de Minaur|A de Minaur]]
}}
==Qualifying==
{{16TeamBracket-Compact-Tennis3|RD1-team01={{flagicon|X}} [[Should Not Appear]]}}
"""

# A schedule row is one physical line in the real wikitext — the cell scanner treats a
# newline as a cell boundary — so these are assembled from fragments rather than wrapped.
_DC_ROW = (
    "|rowspan=4|27 Jul|| rowspan=2 style=\"background:#D4F1C5;\" "
    "|[[2026 Mubadala Citi DC Open|Washington Open]]"
    "<br />[[Washington, D.C.]], United States<br />ATP 500"
    "<br />Hard – $2,469,450 – 48S/24Q/16D"
    "<br />[[2026 Mubadala Citi DC Open – Men's singles|Singles]]"
    " – [[2026 Mubadala Citi DC Open – Men's doubles|Doubles]]"
    " || {{flagicon|AUS}} [[Alex de Minaur]]"
)
_CABOS_ROW = (
    "| rowspan=2 style=\"background:#fff;\" |[[2026 Los Cabos Open|Los Cabos Open]]"
    "<br />[[Los Cabos]], Mexico<br />ATP 250<br />Hard – $909,790 – 28S/16Q/16D"
    "<br />[[2026 Los Cabos Open – Singles|Singles]] || {{flagicon|}} [[Nobody]]"
)
_PARIS_ROW = (
    "| rowspan=2 style=\"background:#e9e9e9;\" |[[2026 Rolex Paris Masters|Paris Masters]]"
    "<br />[[Paris]], France<br />ATP 1000<br />Hard (i) – €6,128,940 – 48S/16Q/24D"
    "<br />[[2026 Rolex Paris Masters – Singles|Singles]]"
)
CALENDAR = "\n".join([
    "{|class=wikitable", "|-", "|+style=\"text-align:left\" | Key", "|[[ATP 500]]", "|}",
    "===July===", "{|class=wikitable", "|-", _DC_ROW, "|-", _CABOS_ROW, "|}",
    "===October===", "{|class=wikitable", "|-", _PARIS_ROW, "|}",
])


# --- draw sheets -----------------------------------------------------------------------

def test_parse_draw_reads_slots_seeds_and_byes():
    slots = wiki.parse_draw(DRAW)
    assert len(slots) == 8                      # a 16TeamBracket half is 8 round-1 slots
    assert [s["slot"] for s in slots] == list(range(1, 9))

    bye = slots[0]                              # RD1 pair 01/02 absent -> a bye
    assert bye["bye"] and bye["a"] == "Alex de Minaur" and bye["b"] is None
    assert bye["seed_a"] == "1"

    played = slots[1]                           # RD1 teams 03/04
    assert (played["a"], played["b"]) == ("Stefanos Tsitsipas", "Marcos Giron")
    assert (played["seed_a"], played["seed_b"]) == ("WC", "Q")
    assert not played.get("bye")

    # Slots with no data at all are partial, not byes, and make the sheet unusable.
    assert all(s.get("partial") for s in slots[4:])
    assert not wiki.is_usable(slots)


def test_parse_draw_ignores_the_qualifying_bracket():
    assert not any("Should Not Appear" in (s.get("a") or "")
                   for s in wiki.parse_draw(DRAW))


def test_clean_player_prefers_the_link_target_and_drops_disambiguation():
    # The display text is abbreviated; the target is the full name. Wikipedia's parenthetical
    # suffixes are article bookkeeping and are also what the live feed omits.
    slots = wiki.parse_draw(DRAW)
    third = slots[2]
    assert third["a"] == "Tommy Paul"                       # not "Tommy Paul (tennis)"
    assert third["b"] == "Martin Damm"                      # not "Martin Damm (born 2003)"
    assert wiki.clean_player("'''{{flagicon|AUS}} [[Alex de Minaur|A de Minaur]]'''") \
        == "Alex de Minaur"


def test_clean_seed_picks_one_tag_out_of_a_multi_tag_cell():
    assert wiki.clean_seed("<small>2/WC</small>") == "2"     # a seed number always wins
    assert wiki.clean_seed("Alt/LL") == "LL"                 # else the standard route
    assert wiki.clean_seed("&nbsp;") is None
    assert wiki.clean_seed("") is None
    assert wiki.clean_seed("Q") == "Q"


def test_is_usable_requires_a_power_of_two_and_no_gaps():
    full = [{"slot": i, "a": f"P{i}", "b": f"Q{i}"} for i in range(1, 5)]
    assert wiki.is_usable(full)
    assert not wiki.is_usable(full[:3])                      # 3 slots: not a power of two
    assert not wiki.is_usable(full[:3] + [{"slot": 4, "partial": True}])


# --- the guard -------------------------------------------------------------------------

def _tour(pairs):
    def side(n):
        return espn.Side(name=n, country=None, winner=False, sets=[])
    ms = [espn.Match(id=str(i), round_rank=1, round_label="Round 1", state="pre", detail="",
                     a=side(a), b=side(b)) for i, (a, b) in enumerate(pairs)]
    return espn.Tournament(id="t", name="Test Open", tier="x", gender="M", best_of=3,
                           matches=ms, city="Testville")


def test_feed_agreement_accepts_the_right_sheet_and_rejects_a_wrong_one():
    sheet = [{"slot": 1, "a": "Ann Alpha", "b": "Bea Beta"},
             {"slot": 2, "a": "Cara Gamma", "b": "Dana Delta"}]
    assert wiki.feed_agreement(sheet, _tour([("Ann Alpha", "Bea Beta"),
                                             ("Cara Gamma", "Dana Delta")])) == 1.0
    # Same players, different pairings — a draw for another event or another year. Two
    # players share a slot in exactly one draw, which is what makes this decisive where
    # comparing the player *set* is not: that would score 100% here.
    assert wiki.feed_agreement(sheet, _tour([("Ann Alpha", "Cara Gamma"),
                                             ("Bea Beta", "Dana Delta")])) == 0.0


def test_feed_agreement_is_zero_without_anything_to_compare():
    assert wiki.feed_agreement([], _tour([("A One", "B Two")])) == 0.0
    assert wiki.feed_agreement([{"slot": 1, "a": "A One", "b": "B Two"}], _tour([])) == 0.0


# --- calendar --------------------------------------------------------------------------

def test_parse_calendar_reads_tier_surface_and_month():
    evs = {e["event"]: e for e in wiki.parse_calendar(CALENDAR)}
    assert set(evs) == {"Washington Open", "Los Cabos Open", "Paris Masters"}

    dc = evs["Washington Open"]
    assert (dc["tier"], dc["surface"], dc["indoor"], dc["month"]) == ("ATP 500", "Hard", False, 7)
    assert dc["city"] == "Washington"
    assert dc["singles_pages"] == ["2026 Mubadala Citi DC Open – Men's singles"]
    # Draw size is read but advisory: this row claims 48 for a draw that is really 32.
    assert dc["draw_size"] == 48

    paris = evs["Paris Masters"]
    assert (paris["tier"], paris["surface"], paris["indoor"], paris["month"]) \
        == ("ATP 1000", "Hard", True, 10)


def test_parse_calendar_skips_the_key_legend():
    # The Key lists every tier as a bare link; those are not tournaments.
    assert all(e["event"] for e in wiki.parse_calendar(CALENDAR))
    assert "ATP 500" not in {e["event"] for e in wiki.parse_calendar(CALENDAR)}


def test_parse_calendar_finds_events_whose_draw_is_not_published_yet():
    # Anchoring on the draw link instead of the tier went blind to every future event —
    # a season page carried nine ATP 1000s and only the five already played had draw pages.
    paris = next(e for e in wiki.parse_calendar(CALENDAR) if e["event"] == "Paris Masters")
    assert paris["tier"] == "ATP 1000"
    assert paris["singles_pages"] == ["2026 Rolex Paris Masters – Singles"]
