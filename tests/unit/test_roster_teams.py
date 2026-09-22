"""Canonical report teams when a player leaves at half and is replaced."""
from __future__ import annotations

from scripts.roster_teams import apply_canonical_teams, canonical_teams

# Team A: 1,2,3 (+4 who leaves at half). Team B: 5,6,7.
# Half 1: A on side 2, B on side 1.   Half 2: sides swap, 8 replaces 4.
H1 = [{"half": 1, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (1, 2, 3, 4)] + \
     [{"half": 1, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (5, 6, 7)]
H2 = [{"half": 2, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (1, 2, 3, 8)] + \
     [{"half": 2, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (5, 6, 7)]


def roster(**team_by_pid):
    return [{"player_id": int(pid), "team": team} for pid, team in team_by_pid.items()]


def test_the_half_one_leaver_is_filed_with_his_own_team():
    # The daemon left player 4 on side 2 -- his half-1 side, which in half 2
    # is the opponent's.
    got = canonical_teams(H1 + H2)
    assert got[4] == 1, "the leaver belongs with 1,2,3"
    assert {got[p] for p in (1, 2, 3, 8)} == {1}
    assert {got[p] for p in (5, 6, 7)} == {2}


def test_players_who_played_the_final_half_keep_their_side():
    players = roster(**{"1": 1, "2": 1, "3": 1, "8": 1, "5": 2, "6": 2, "7": 2, "4": 2})
    out = {p["player_id"]: p for p in apply_canonical_teams(players, H1 + H2)}
    assert all("roster_team" not in out[p] for p in (1, 2, 3, 8, 5, 6, 7))
    assert out[4]["team"] == 1 and out[4]["roster_team"] == 2


def test_input_rows_are_not_mutated():
    players = roster(**{"4": 2})
    apply_canonical_teams(players, H1 + H2)
    assert players[0]["team"] == 2


def test_one_half_or_no_life_feed_leaves_the_roster_alone():
    players = roster(**{"4": 2, "1": 2})
    for feed in (None, [], H1):
        out = apply_canonical_teams(players, feed)
        assert [p["team"] for p in out] == [2, 2]
        assert all("roster_team" not in p for p in out)


def test_a_half_played_on_the_same_sides_is_not_flipped():
    same = [{"half": 2, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (1, 2, 3)] + \
           [{"half": 2, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (5, 6, 7)]
    got = canonical_teams(H1 + same)
    assert got[4] == 2 and got[1] == 2 and got[5] == 1


def test_three_halves_carry_back_through_each_swap():
    h3 = [{"half": 3, "player_id": p, "team": 2, "boundary_kind": "start"} for p in (1, 2, 3)] + \
         [{"half": 3, "player_id": p, "team": 1, "boundary_kind": "start"} for p in (5, 6, 7)]
    got = canonical_teams(H1 + H2 + h3)
    # Final half is 3: team A is side 2 there, so A's label is 2.
    assert {got[p] for p in (1, 2, 3)} == {2} and got[4] == 2
    assert {got[p] for p in (5, 6, 7)} == {1}
