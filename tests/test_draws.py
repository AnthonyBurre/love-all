"""Draw-fixture slot scaffolding: live matches overlaid on committed R1 slot order."""

from match_charting_project.live import draws, espn


def _m(id, rank, label, a, b, winner=None):
    def side(n):
        return espn.Side(name=n, country=None, winner=(n == winner), sets=[])
    return espn.Match(id=id, round_rank=rank, round_label=label,
                      state="post" if winner else "pre", detail="", a=side(a), b=side(b))


def _tour(matches):
    return espn.Tournament(id="t", name="Test Open", tier="Grand Slam", gender="M",
                           best_of=5, matches=matches)


FX = {"tournament": "Test Open", "gender": "M", "season": 2026, "r1": [
    {"slot": 1, "a": "Ann Alpha", "b": "Bea Beta", "seed_a": "1", "seed_b": None},
    {"slot": 2, "a": "Cara Gamma", "b": "Dana Delta", "seed_a": None, "seed_b": "Q"},
    {"slot": 3, "a": "Eve Epsilon", "b": "Faye Zeta", "seed_a": None, "seed_b": None},
    {"slot": 4, "a": "Gail Eta", "b": "Hope Theta", "seed_a": "2", "seed_b": None},
]}


def test_slot_rounds_full_scaffold_and_feeds():
    # ESPN feed order scrambled; SF half-known; final TBD (and absent placeholders synthesized).
    t = _tour([
        _m("f", 100, "Final", "TBD", "TBD"),
        _m("s2", 99, "Semifinal", "TBD", "Gail Eta"),
        _m("r3", 1, "Round 1", "Eve Epsilon", "Faye Zeta", winner="Eve Epsilon"),
        _m("r1", 1, "Round 1", "Ann Alpha", "Bea Beta", winner="Ann Alpha"),
        _m("r4", 1, "Round 1", "Gail Eta", "Hope Theta", winner="Gail Eta"),
        _m("r2", 1, "Round 1", "Cara Gamma", "Dana Delta"),
    ])
    out = draws.slot_rounds(t, FX)
    assert [len(r["matches"]) for r in out] == [4, 2, 1]

    r1 = out[0]["matches"]
    assert [m.id for m in r1] == ["r1", "r2", "r3", "r4"]          # fixture slot order
    assert r1[0].a.seed == "1" and r1[1].b.seed == "Q"             # seeds attached

    sf = out[1]["matches"]
    assert getattr(sf[0], "placeholder", False)                    # SF slot 1 undecided
    assert sf[0].id == "slot-2-1"
    assert sf[1].id == "s2"                                        # Gail traces to SF slot 2

    assert r1[0].feeds == "slot-2-1" and r1[1].feeds == "slot-2-1"
    assert r1[2].feeds == "s2" and r1[3].feeds == "s2"             # feeds point at live ids
    assert sf[0].feeds == "f" and sf[1].feeds == "f"
    assert out[2]["matches"][0].id == "f" and out[2]["matches"][0].feeds is None


def test_slot_rounds_fuzzy_names_and_bail_on_conflict():
    # Accents/spacing differences still place; a slot double-claim distrusts everything.
    t = _tour([
        _m("f", 100, "Final", "TBD", "TBD"),
        _m("s1", 99, "Semifinal", "TBD", "TBD"),
        _m("s2", 99, "Semifinal", "TBD", "TBD"),
        _m("r1", 1, "Round 1", "Ánn Álpha", "Bea Beta"),
        _m("r2", 1, "Round 1", "CaraGamma", "Dana Delta"),
        _m("r3", 1, "Round 1", "Eve Epsilon", "Faye Zeta"),
        _m("r4", 1, "Round 1", "Gail Eta", "Hope Theta"),
    ])
    out = draws.slot_rounds(t, FX)
    assert [m.id for m in out[0]["matches"]] == ["r1", "r2", "r3", "r4"]

    dup = _tour([
        _m("f", 100, "Final", "TBD", "TBD"),
        _m("s1", 99, "Semifinal", "TBD", "TBD"),
        _m("s2", 99, "Semifinal", "TBD", "TBD"),
        _m("x1", 1, "Round 1", "Ann Alpha", "Dana Delta"),         # claims slot 1 (Ann)
        _m("x2", 1, "Round 1", "Bea Beta", "Cara Gamma"),          # votes conflict too
        _m("x3", 1, "Round 1", "Eve Epsilon", "Faye Zeta"),
        _m("x4", 1, "Round 1", "Gail Eta", "Hope Theta"),
    ])
    # x1 votes {1 (Ann), 2 (Dana)} -> conflicting, unplaced; x2 votes {1, 2} -> unplaced.
    out2 = draws.slot_rounds(dup, FX)
    ids = [m.id for m in out2[0]["matches"]]
    assert ids[0].startswith("slot-") and ids[1].startswith("slot-")
    assert ids[2:] == ["x3", "x4"]


# A field short of a power of two — 28 or 48 players — seeds its top names straight into
# round two. The fixture records those slots with one entrant and no opponent.
FX_BYES = {"tournament": "Test Open", "gender": "M", "season": 2026, "r1": [
    {"slot": 1, "a": "Ann Alpha", "b": None, "seed_a": "1", "seed_b": None, "bye": True},
    {"slot": 2, "a": "Cara Gamma", "b": "Dana Delta", "seed_a": None, "seed_b": "Q"},
    {"slot": 3, "a": "Eve Epsilon", "b": "Faye Zeta", "seed_a": None, "seed_b": None},
    {"slot": 4, "a": "Gail Eta", "b": None, "seed_a": "2", "seed_b": None, "bye": True},
]}


def test_byes_render_as_the_entrant_already_through():
    # Only two round-1 matches are ever played, so the feed carries two — but the scaffold
    # still has four slots, and the two spare ones are byes, not undecided pairings.
    t = _tour([
        _m("f", 100, "Final", "TBD", "TBD"),
        _m("s1", 99, "Semifinal", "Ann Alpha", "TBD"),
        _m("s2", 99, "Semifinal", "TBD", "Gail Eta"),
        _m("r2", 1, "Round 1", "Cara Gamma", "Dana Delta", winner="Cara Gamma"),
        _m("r3", 1, "Round 1", "Eve Epsilon", "Faye Zeta"),
    ])
    out = draws.slot_rounds(t, FX_BYES)
    assert [len(r["matches"]) for r in out] == [4, 2, 1]      # full power-of-two scaffold

    r1 = out[0]["matches"]
    bye, played = r1[0], r1[1]
    assert bye.bye and bye.placeholder                        # structural, never clickable
    assert (bye.a.name, bye.b.name) == ("Ann Alpha", draws.BYE)
    assert bye.a.seed == "1" and bye.b.seed is None           # the marker takes no seed
    assert not getattr(played, "bye", False) and played.id == "r2"

    assert r1[3].bye and r1[3].a.name == "Gail Eta" and r1[3].a.seed == "2"
    # A bye still feeds its round-2 match, so the path to the final stays wired.
    assert bye.feeds == "s1" and r1[3].feeds == "s2"


def test_byes_only_apply_to_round_one():
    # Later rounds always pair two winners; an undecided one there is a TBD, not a bye.
    t = _tour([
        _m("f", 100, "Final", "TBD", "TBD"),
        _m("s1", 99, "Semifinal", "TBD", "TBD"),
        _m("s2", 99, "Semifinal", "TBD", "TBD"),
        _m("r2", 1, "Round 1", "Cara Gamma", "Dana Delta"),
        _m("r3", 1, "Round 1", "Eve Epsilon", "Faye Zeta"),
    ])
    out = draws.slot_rounds(t, FX_BYES)
    for m in out[1]["matches"]:
        assert not getattr(m, "bye", False)
        assert (m.a.name, m.b.name) == ("TBD", "TBD")


def test_bye_slots_reads_only_one_sided_entries():
    assert draws._bye_slots(FX_BYES) == {1: "Ann Alpha", 4: "Gail Eta"}
    assert draws._bye_slots(FX) == {}                         # a full draw has none


def test_cached_draw_sheet_feeds_the_scaffold():
    """Draw sheets come from ``live.feeds`` (Wikipedia, cached) rather than committed files,
    so check the handoff shape rather than a fixture on disk."""
    from match_charting_project.live import feeds

    store = {"draws": {"test open|M": {"tournament": "Test Open", "gender": "M",
                                       "source_page": "2026 Test Open – Men's singles",
                                       "r1": FX_BYES["r1"]}}}
    t = _tour([])
    t.city = "Test Open"
    fx = feeds.fixture_for(t, store)
    assert fx and len(fx["r1"]) == 4
    assert len(draws._bye_slots(fx)) == 2          # the sheet's byes survive the handoff
    t.city = "Somewhere Else"
    assert feeds.fixture_for(t, store) is None
