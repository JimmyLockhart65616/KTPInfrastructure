"""Unit tests for pure bracket slot resolution (4-bye single-elim + consolation)."""
from app.bracket import resolve_slots

# standings rank -> team id (use 100+rank for clarity)
RANK = {r: 100 + r for r in range(1, 11)}


def test_initial_layout_from_seeds():
    s = resolve_slots(RANK, {})
    assert s["PI1"] == (105, 110)   # seed 5 v seed 10
    assert s["PI2"] == (106, 109)
    assert s["PI3"] == (107, 108)
    assert s["QF1"] == (104, None)  # seed 4 waits on W:PI1
    assert s["QF2"] == (103, None)
    assert s["QF3"] == (102, None)
    assert s["SF1"] == (101, None)  # seed 1 byes the QF, waits on W:QF1
    assert s["F"] == (None, None)


def test_seed1_double_bye_never_in_the_qf():
    # seed 1 (101) appears only in SF1, never in any quarterfinal
    s = resolve_slots(RANK, {})
    qf_sides = {x for k in ("QF1", "QF2", "QF3") for x in s[k]}
    assert 101 not in qf_sides
    assert s["SF1"][0] == 101


def test_playin_winners_feed_qf():
    s = resolve_slots(RANK, {"PI1": (105, 110), "PI2": (106, 109), "PI3": (107, 108)})
    assert s["QF1"] == (104, 105)   # seed 4 v winner PI1
    assert s["QF2"] == (103, 106)
    assert s["QF3"] == (102, 107)
    assert s["PLS"] == (110, 109)   # the play-in losers start the consolation


def test_qf_losers_into_lower_semi_and_seed1_into_sf():
    outcomes = {
        "PI1": (105, 110), "PI2": (106, 109), "PI3": (107, 108),
        "QF1": (104, 105), "QF2": (103, 106), "QF3": (102, 107),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["SF1"] == (101, 104)   # seed 1 (bye) v winner QF1
    assert s["SF2"] == (103, 102)   # winner QF2 v winner QF3
    assert s["LS1"] == (105, 106)   # the two lower QF losers
    assert s["P56"] == (107, None)  # highest QF loser waits on W:LS1


def test_sf_losers_play_each_other_for_third():
    outcomes = {
        "PI1": (105, 110), "PI2": (106, 109), "PI3": (107, 108),
        "QF1": (104, 105), "QF2": (103, 106), "QF3": (102, 107),
        "SF1": (101, 104), "SF2": (102, 103),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["P34"] == (104, 103)   # the two SF losers, not dropped anywhere
    assert s["F"] == (101, 102)


_FULL = {
    "PI1": (105, 110), "PI2": (106, 109), "PI3": (107, 108),
    "QF1": (104, 105), "QF2": (103, 106), "QF3": (102, 107),
    "SF1": (101, 104), "SF2": (102, 103),
    "F":   (101, 102),
    "P34": (104, 103),
    "LS1": (105, 106),
    "PLS": (110, 109),
}


def test_consolation_tiers_resolve():
    s = resolve_slots(RANK, _FULL)
    assert s["P56"] == (107, 105)   # L:QF3 v W:LS1 → 5th/6th
    assert s["P89"] == (108, 110)   # L:PI3 v W:PLS → 8th/9th


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
