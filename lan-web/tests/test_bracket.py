"""Unit tests for pure bracket slot resolution."""
from app.bracket import resolve_slots

# standings rank -> team id (use 100+rank for clarity)
RANK = {r: 100 + r for r in range(1, 11)}


def test_initial_layout_from_seeds():
    s = resolve_slots(RANK, {})
    assert s["QF1"] == (103, 106)   # seed 3 v seed 6
    assert s["QF2"] == (104, 105)   # seed 4 v seed 5
    assert s["SF1"] == (101, None)  # seed 1 waits on W:QF2
    assert s["SF2"] == (102, None)  # seed 2 waits on W:QF1
    assert s["F"] == (None, None)
    assert s["PA"] == (107, 110)    # seed 7 v seed 10
    assert s["PB"] == (108, 109)
    assert s["LSF1"] == (None, None)  # L:QF2 and W:PA both undecided
    assert s["LF"] == (None, None)


def test_qf_losers_drop_into_lower_semis():
    outcomes = {
        "QF1": (103, 106),  # 103 beats 106
        "QF2": (104, 105),  # 104 beats 105
        "PA": (107, 110),
        "PB": (108, 109),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["SF1"] == (101, 104)   # seed 1 v winner QF2
    assert s["SF2"] == (102, 103)   # seed 2 v winner QF1
    assert s["LSF1"] == (105, 107)  # loser QF2 v winner Play-in A
    assert s["LSF2"] == (106, 108)  # loser QF1 v winner Play-in B


def test_finals_resolve():
    outcomes = {
        "QF1": (103, 106), "QF2": (104, 105),
        "SF1": (101, 104), "SF2": (102, 103),
        "PA": (107, 110), "PB": (108, 109),
        "LSF1": (105, 107), "LSF2": (108, 106),
    }
    s = resolve_slots(RANK, outcomes)
    assert s["F"] == (101, 102)     # the two SF winners
    assert s["LF"] == (105, 108)    # the two lower-SF winners


def test_qf_loser_never_meets_upper_again():
    # a QF loser only appears in the lower bracket, not the upper SF/F
    outcomes = {"QF1": (103, 106), "QF2": (104, 105)}
    s = resolve_slots(RANK, outcomes)
    upper_teams = {t for k in ("SF1", "SF2") for t in s[k] if t}
    assert 105 not in upper_teams and 106 not in upper_teams  # losers
    assert 105 in s["LSF1"] and 106 in s["LSF2"]


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
