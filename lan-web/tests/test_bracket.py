"""Unit tests for pure bracket slot resolution (single-elim + consolation)."""
from app.bracket import resolve_slots

# standings rank -> team id (use 100+rank for clarity)
RANK = {r: 100 + r for r in range(1, 11)}


def test_initial_layout_from_seeds():
    s = resolve_slots(RANK, {})
    assert s["PI1"] == (107, 110)   # seed 7 v seed 10
    assert s["PI2"] == (108, 109)   # seed 8 v seed 9
    assert s["QF1"] == (101, None)  # seed 1 waits on W:PI2
    assert s["QF2"] == (104, 105)   # seed 4 v seed 5 (both byes)
    assert s["QF3"] == (103, 106)   # seed 3 v seed 6
    assert s["QF4"] == (102, None)  # seed 2 waits on W:PI1
    assert s["SF1"] == (None, None)
    assert s["F"] == (None, None)


def test_playin_winners_feed_top_seeds():
    s = resolve_slots(RANK, {"PI1": (107, 110), "PI2": (108, 109)})
    assert s["QF1"] == (101, 108)   # seed 1 v winner PI2
    assert s["QF4"] == (102, 107)   # seed 2 v winner PI1
    assert s["P910"] == (110, 109)  # the two play-in losers settle 9/10


def test_qf_losers_into_lower_semis():
    outcomes = {
        "PI1": (107, 110), "PI2": (108, 109),
        "QF1": (101, 108), "QF2": (104, 105), "QF3": (103, 106), "QF4": (102, 107),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["SF1"] == (101, 104)   # W:QF1 v W:QF2
    assert s["SF2"] == (103, 102)   # W:QF3 v W:QF4
    assert s["LS1"] == (108, 107)   # L:QF1 v L:QF4
    assert s["LS2"] == (105, 106)   # L:QF2 v L:QF3


def test_sf_losers_play_each_other_for_third():
    outcomes = {
        "PI1": (107, 110), "PI2": (108, 109),
        "QF1": (101, 108), "QF2": (104, 105), "QF3": (103, 106), "QF4": (102, 107),
        "SF1": (101, 104), "SF2": (102, 103),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["P34"] == (104, 103)   # the two SF losers, not dropped anywhere
    assert s["F"] == (101, 102)     # the two SF winners


_FULL = {
    "PI1": (107, 110), "PI2": (108, 109),
    "QF1": (101, 108), "QF2": (104, 105), "QF3": (103, 106), "QF4": (102, 107),
    "SF1": (101, 104), "SF2": (102, 103),
    "F":   (101, 102),
    "P34": (104, 103),
    "LS1": (108, 107), "LS2": (105, 106),
}


def test_placement_tiers_resolve():
    s = resolve_slots(RANK, _FULL)
    assert s["P56"]  == (108, 105)   # W:LS1 v W:LS2 → 5th/6th
    assert s["P78"]  == (107, 106)   # L:LS1 v L:LS2 → 7th/8th
    assert s["P910"] == (110, 109)   # L:PI1 v L:PI2 → 9th/10th


def test_consolation_never_touches_the_final():
    # the Final is fed only by the two semifinals; no placement key feeds it
    s = resolve_slots(RANK, _FULL)
    assert s["F"] == (101, 102)


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
