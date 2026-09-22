"""Engine-side -> report-team translation layer over flag_swing.sides_by_half."""
from __future__ import annotations

from scripts.report_team_convention import (
    report_team1_engine_side,
    translate_capouts,
    translate_map_control,
    translate_team_series,
)

ROSTER = [
    {"player_id": 1, "team": 1},
    {"player_id": 2, "team": 1},
    {"player_id": 3, "team": 2},
    {"player_id": 4, "team": 2},
]


def life(half, pid, team):
    return {"half": half, "player_id": pid, "team": team}


def test_report_team1_engine_side_resolves_the_swapped_half():
    # Report team 1 (players 1, 2) played engine Axis (2) in half 1, and
    # (as ktp_match_players always shows) engine Allies (1) in half 2.
    lives = [life(1, 1, 2), life(1, 2, 2), life(1, 3, 1), life(1, 4, 1),
             life(2, 1, 1), life(2, 2, 1), life(2, 3, 2), life(2, 4, 2)]
    result = report_team1_engine_side(lives, ROSTER)
    assert result == {1: 2, 2: 1}


def test_disagreeing_report_team1_players_drop_the_half():
    lives = [life(1, 1, 1), life(1, 2, 2)]  # both report team 1, split sides
    assert report_team1_engine_side(lives, ROSTER) == {}


def test_translate_map_control_mirrors_when_report_team1_played_engine_side_2():
    mc = {"halves": {"1": [[0.0, 0.2], [4.0, 0.8]]},
          "orientation_by_half": {"1": "team1_at_arc0"},
          "mean_control_team1": 0.5, "caveats": []}
    translate_map_control(mc, {1: 2})
    assert mc["halves"]["1"] == [[0.0, 0.8], [4.0, 0.2]]
    assert mc["orientation_by_half"]["1"] == "team2_at_arc0"
    assert mc["mean_control_team1"] == 0.5


def test_translate_map_control_keeps_engine_side_1_as_is():
    mc = {"halves": {"1": [[0.0, 0.3]]}, "orientation_by_half": {"1": "team1_at_arc0"},
          "mean_control_team1": 0.3, "caveats": []}
    translate_map_control(mc, {1: 1})
    assert mc["halves"]["1"] == [[0.0, 0.3]]
    assert mc["orientation_by_half"]["1"] == "team1_at_arc0"


def test_translate_map_control_drops_unresolved_half_with_a_caveat():
    mc = {"halves": {"1": [[0.0, 0.5]], "2": [[0.0, 0.4]]},
          "orientation_by_half": {"1": "team1_at_arc0", "2": "team1_at_arc0"},
          "mean_control_team1": 0.45, "caveats": []}
    translate_map_control(mc, {2: 1})  # half 1 unresolved
    assert "1" not in mc["halves"]
    assert "2" in mc["halves"]
    assert any("1" in c for c in mc["caveats"])


def test_translate_team_series_swaps_the_differential_when_engine_side_flips():
    rows = [{"team": 1, "half": 1, "metric": "flag_differential", "points": [[0, 2]]},
            {"team": 2, "half": 1, "metric": "flag_differential", "points": [[0, -2]]}]
    out, dropped = translate_team_series(rows, {1: 2})
    by_team = {r["team"]: r["points"] for r in out}
    assert by_team[1] == [[0, -2]]  # report team 1 gets engine team 2's series
    assert by_team[2] == [[0, 2]]
    assert dropped == []


def test_translate_team_series_drops_a_half_with_no_resolved_side():
    rows = [{"team": 1, "half": 1, "metric": "flag_differential", "points": [[0, 1]]},
            {"team": 2, "half": 1, "metric": "flag_differential", "points": [[0, -1]]}]
    out, dropped = translate_team_series(rows, {})
    assert out == []
    assert dropped == [1]


def test_translate_capouts_relabels_team_to_report_convention():
    capouts = [{"half": 1, "game_time": 30.0, "team": 2}]
    out = translate_capouts(capouts, {1: 2})
    assert out == [{"half": 1, "game_time": 30.0, "team": 1}]


def test_translate_capouts_drops_an_unresolved_half():
    capouts = [{"half": 1, "game_time": 30.0, "team": 2}]
    assert translate_capouts(capouts, {}) == []
