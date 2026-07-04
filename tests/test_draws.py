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


def test_find_fixture_matches_real_file():
    fx = draws.find_fixture("Wimbledon", "M")
    if fx is None:                                 # fixtures live in data/; absent in bare checkouts
        return
    assert len(fx["r1"]) == 64
