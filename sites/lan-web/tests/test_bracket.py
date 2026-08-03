"""Unit tests for pure bracket slot resolution (single-elim + consolation)."""
from app import bracket as B
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
    assert s["LS1"] == (108, 105)   # L:QF1 v L:QF2
    assert s["LS2"] == (106, 107)   # L:QF3 v L:QF4


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
    "LS1": (108, 105), "LS2": (106, 107),
}


def test_placement_tiers_resolve():
    s = resolve_slots(RANK, _FULL)
    assert s["P56"]  == (108, 106)   # W:LS1 v W:LS2 → 5th/6th
    assert s["P78"]  == (105, 107)   # L:LS1 v L:LS2 → 7th/8th
    assert s["P910"] == (110, 109)   # L:PI1 v L:PI2 → 9th/10th


def test_consolation_never_touches_the_final():
    # the Final is fed only by the two semifinals; no placement key feeds it
    s = resolve_slots(RANK, _FULL)
    assert s["F"] == (101, 102)


# ── dynamic layouts: every count yields a complete 1..N ranking ───────────
def _play_out(n, upset=None):
    """Resolve a full bracket for n teams (team id == seed). Favorite (lower
    seed) wins each match unless its mkey is in `upset`. -> {place: team_id}."""
    upset = upset or set()
    matches = B.LAYOUTS[n]["matches"]
    rank = {i: i for i in range(1, n + 1)}
    out: dict[str, tuple] = {}

    def side(src):
        kind, ref = src.split(":")
        if kind == "seed":
            return rank.get(int(ref))
        if ref in out:
            w, l = out[ref]
            return w if kind == "W" else l
        return None

    changed = True
    while changed:
        changed = False
        for m in matches:
            if m["key"] in out:
                continue
            a, b = side(m["a"]), side(m["b"])
            if a and b:
                w = max(a, b) if m["key"] in upset else min(a, b)
                out[m["key"]] = (w, b if w == a else a)
                changed = True
    return {pl: side(src) for pl, src in B.LAYOUTS[n]["placement"]}


def test_every_layout_produces_full_ranking():
    for n in (10, 11, 12):
        places = _play_out(n)
        assert len(places) == n
        assert set(places.values()) == set(range(1, n + 1))   # a clean permutation
        assert places[1] == 1                                  # chalk: seed 1 wins


def test_full_ranking_holds_under_upsets():
    for n in (10, 11, 12):
        places = _play_out(n, upset={"F", "P34", "SF1", "PI1"})
        assert set(places.values()) == set(range(1, n + 1))


def test_layout_keys_fit_db_column():
    # lan_bracket.mkey is VARCHAR(8); stage order must cover every stage used.
    for n, lay in B.LAYOUTS.items():
        for m in lay["matches"]:
            assert len(m["key"]) <= 8
            assert m["stage"] in B.STAGE_ORDER


def test_playin_is_bo1_in_every_layout():
    """The play-in is best-of-one and gets a live veto like any other match.

    It used to be pinned to the one map Saturday skipped (railroad2), which is why
    this is worth pinning: re-hardcoding a map would show up as a best_of change or
    a preset map here first."""
    for layout in (B._L10, B._L11, B._L12):
        pi = [m for m in layout["matches"] if m["stage"] == "PI"]
        assert pi, "every layout must have play-in matches"
        for m in pi:
            assert m["best_of"] == 1, f"{m['key']} should be BO1, got {m['best_of']}"
            assert "map" not in m, f"{m['key']} must not carry a preset map"


def test_playin_veto_uses_the_whole_pool_and_yields_one_map():
    """BO1 veto bans down to a single map over the full pool — no separate play-in
    pool, so a map skipped on Saturday is still eligible on Sunday."""
    from app import veto, schedule
    pool = len(schedule.COMP_MAPS)
    seq = veto.sequence(pool, 1)
    bans = [s for s in seq if s["action"] == "ban"]
    assert len(bans) == pool - 1                     # exactly one map survives
    assert seq[0]["actor"] == "TS"                   # top seed bans first
    assert seq[-1] == {"actor": "LS", "action": "decider"}   # lower seed picks the side
    assert not any(s["action"] == "pick" for s in seq)       # picks are BO3-only


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

def _chalk_participants(n):
    """Play every match chalk (better seed wins); return {mkey: (seed_a, seed_b)}
    of who CONTESTED it. Team id == seed here, so sums are seed sums."""
    matches = B.LAYOUTS[n]["matches"]
    out, parts = {}, {}

    def side(src):
        kind, ref = src.split(":")
        if kind == "seed":
            return int(ref) if int(ref) <= n else None
        if ref in out:
            w, l = out[ref]
            return w if kind == "W" else l
        return None

    changed = True
    while changed:
        changed = False
        for m in matches:
            if m["key"] in out:
                continue
            a, b = side(m["a"]), side(m["b"])
            if a and b:
                parts[m["key"]] = (a, b)
                out[m["key"]] = (min(a, b), max(a, b))
                changed = True
    return parts


def test_consolation_pairings_are_reseeded_not_concentrated():
    """Each consolation semi must draw one strong and one weak loser.

    Pairing both top-half QF losers into the same semi guarantees a higher seed
    contests 7/8 while a weaker one contests 5/6 — decided by the pairing rather
    than by results. N=10 sat at 15/11 and N=11/N=12 at 14/12 until 2026-08-02.
    The rule is re-seed best-vs-worst; N=12's lower play-in already did this with
    PI1+PI4 / PI2+PI3, which is why "mirror the upper bracket" is the wrong
    generalisation to reach for here.
    """
    for n in (10, 11, 12):
        p = _chalk_participants(n)
        a, b = sum(p["LS1"]), sum(p["LS2"])
        assert a == b, f"N={n} lower semis unbalanced: LS1={p['LS1']}={a} LS2={p['LS2']}={b}"


def test_playin_loser_bracket_byes_the_strongest():
    """N=11 byes one play-in loser straight into 9/10 — it must be the best of
    them. It used to be L:PI1 (the 6v11 loser, expected seed 11), which guaranteed
    a 9 or 10 seed finished 11th."""
    p = _chalk_participants(11)
    losers = {max(p[k]) for k in ("PI1", "PI2", "PI3")}
    bye = (losers - set(p["P11"])).pop()
    assert bye == min(losers), f"bye went to seed {bye}, strongest loser is {min(losers)}"

    q = _chalk_participants(12)   # N=12 has no bye; its lower play-in re-seeds
    assert sum(q["LPI1"]) == sum(q["LPI2"]), f"LPI1={q['LPI1']} LPI2={q['LPI2']}"
