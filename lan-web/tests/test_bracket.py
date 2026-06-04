"""Unit tests for pure bracket slot resolution (true double-elimination)."""
from app.bracket import resolve_slots

# standings rank -> team id (use 100+rank for clarity)
RANK = {r: 100 + r for r in range(1, 11)}


def test_initial_layout_from_seeds():
    s = resolve_slots(RANK, {})
    assert s["QF1"] == (103, 106)   # seed 3 v seed 6
    assert s["QF2"] == (104, 105)   # seed 4 v seed 5
    assert s["SF1"] == (101, None)  # seed 1 waits on W:QF2
    assert s["SF2"] == (102, None)  # seed 2 waits on W:QF1
    assert s["UF"] == (None, None)
    assert s["PA"] == (107, 110)    # seed 7 v seed 10
    assert s["PB"] == (108, 109)
    assert s["LB1"] == (None, None)  # L:QF1 and W:PA both undecided
    assert s["LF"] == (None, None)


def test_qf_losers_drop_into_lower_r2():
    outcomes = {
        "QF1": (103, 106), "QF2": (104, 105),
        "PA": (107, 110), "PB": (108, 109),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["SF1"] == (101, 104)   # seed 1 v winner QF2
    assert s["SF2"] == (102, 103)   # seed 2 v winner QF1
    assert s["LB1"] == (106, 107)   # loser QF1 v winner Play-in A
    assert s["LB2"] == (105, 108)   # loser QF2 v winner Play-in B


def test_sf_losers_drop_into_lower_r3():
    outcomes = {
        "QF1": (103, 106), "QF2": (104, 105),
        "SF1": (101, 104), "SF2": (102, 103),
        "PA": (107, 110), "PB": (108, 109),
        "LB1": (107, 106), "LB2": (108, 105),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["LB3"] == (104, 108)   # loser SF1 v winner LB2  (true 2nd life for an SF loser)
    assert s["LB4"] == (103, 107)   # loser SF2 v winner LB1


def test_upper_final_loser_drops_to_lower_final():
    outcomes = {
        "QF1": (103, 106), "QF2": (104, 105),
        "SF1": (101, 104), "SF2": (102, 103),
        "UF":  (101, 102),
        "PA": (107, 110), "PB": (108, 109),
        "LB1": (107, 106), "LB2": (108, 105),
        "LB3": (108, 104), "LB4": (107, 103),
        "LSF": (108, 107),
    }
    s = resolve_slots(RANK, outcomes)
    # seed 2 (102) lost the Upper Final but lands in the Lower Final — second life
    assert s["LF"] == (102, 108)


# Full run-through so the Grand Final + every placement match resolve.
_FULL = {
    "QF1": (103, 106), "QF2": (104, 105),
    "SF1": (101, 104), "SF2": (102, 103),
    "UF":  (101, 102),
    "PA": (107, 110), "PB": (108, 109),
    "LB1": (107, 106), "LB2": (108, 105),
    "LB3": (108, 104), "LB4": (107, 103),
    "LSF": (108, 107),
    "LF":  (102, 108),     # the dropped UF loser (102) wins the lower bracket
}


def test_grand_final_reunites_upper_and_lower_champions():
    s = resolve_slots(RANK, _FULL)
    assert s["GF"] == (101, 102)   # upper champ (W:UF) v lower champ (W:LF) — a UF rematch


def test_placement_matches_pair_same_round_losers():
    s = resolve_slots(RANK, _FULL)
    assert s["P56"]  == (104, 103)   # L:LB3 v L:LB4 → 5th/6th
    assert s["P78"]  == (106, 105)   # L:LB1 v L:LB2 → 7th/8th
    assert s["P910"] == (110, 109)   # L:PA  v L:PB  → 9th/10th


def test_grand_final_waits_on_both_finals():
    partial = {**_FULL}
    del partial["LF"]
    s = resolve_slots(RANK, partial)
    assert s["GF"] == (101, None)   # upper champ known, lower side waiting


if __name__ == "__main__":
    import sys
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in funcs:
        try:
            fn(); print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failed += 1; print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
