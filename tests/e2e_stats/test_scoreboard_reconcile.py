"""The reconciler's judgement, and the map-fact parser's reading of the configs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import map_scoring_facts as facts  # noqa: E402
import scoreboard_reconcile as recon  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[0] / "fixtures" / "scoreboard" / "1789348403-ATL2.json"


def _stats(tmp_path: Path, rows: list[dict]) -> Path:
    header = ["half", "player_name", "kills", "deaths", "tk_deaths", "suicides",
              "caps", "objscore", "objscore_stored"]
    lines = ["\t".join(header)]
    lines += ["\t".join(str(r.get(k, 0)) for k in header) for r in rows]
    path = tmp_path / "stats.tsv"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_exact_match_reports_no_differences(tmp_path):
    board = {"match_id": "m", "halves": {"1": {"players": [
        {"name": "cope ~ ddorito", "side": "axis", "kills": 25, "deaths": 19, "objscore": 4}]}}}
    stats = recon.read_stats(_stats(tmp_path, [
        {"half": 1, "player_name": "cope ~ ddorito", "kills": 25, "deaths": 19,
         "objscore": 4, "objscore_stored": 4}]))
    lines, differences = recon.reconcile(board, stats)
    assert differences == 0
    assert "No differences" in "\n".join(lines)


def test_names_match_across_tag_noise(tmp_path):
    # The screenshot and the database spell the same player differently often
    # enough that exact matching would report a phantom difference.
    board = {"match_id": "m", "halves": {"1": {"players": [
        {"name": "o8-[_kroD-_]", "kills": 17, "deaths": 31, "objscore": 1}]}}}
    stats = recon.read_stats(_stats(tmp_path, [
        {"half": 1, "player_name": "o8-[_KROD-_]", "kills": 17, "deaths": 31,
         "objscore": 1, "objscore_stored": 0}]))
    _, differences = recon.reconcile(board, stats)
    assert differences == 0


def test_stored_objscore_disagreement_is_flagged_but_not_a_difference(tmp_path):
    # dodx's savedScore undercount must be visible without being counted as a
    # reconciliation failure: the computed column is the one that is right.
    board = {"match_id": "m", "halves": {"1": {"players": [
        {"name": "p", "kills": 1, "deaths": 1, "objscore": 4}]}}}
    stats = recon.read_stats(_stats(tmp_path, [
        {"half": 1, "player_name": "p", "kills": 1, "deaths": 1,
         "objscore": 4, "objscore_stored": 3}]))
    lines, differences = recon.reconcile(board, stats)
    assert differences == 0
    assert any("3 ⚠" in line for line in lines)


def test_differences_are_signed_against_the_database(tmp_path):
    board = {"match_id": "m", "halves": {"1": {"players": [
        {"name": "p", "kills": 35, "deaths": 19, "objscore": 3}]}}}
    stats = recon.read_stats(_stats(tmp_path, [
        {"half": 1, "player_name": "p", "kills": 37, "deaths": 19, "objscore": 3}]))
    lines, differences = recon.reconcile(board, stats)
    assert differences == 1
    assert any("**+2**" in line for line in lines)


def test_missing_player_is_a_difference_not_a_crash(tmp_path):
    board = {"match_id": "m", "halves": {"1": {"players": [
        {"name": "ghost", "kills": 1, "deaths": 1, "objscore": 1}]}}}
    _, differences = recon.reconcile(board, recon.read_stats(_stats(tmp_path, [])))
    assert differences == 1


def test_real_fixture_covers_both_halves_and_both_sides():
    board = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(board["halves"]) == {"1", "2"}
    for half in board["halves"].values():
        sides = {p["side"] for p in half["players"]}
        assert sides == {"allies", "axis"}
        assert len(half["players"]) == 12
    # Sides swap at halftime; the same player is on opposite sides across halves.
    first = {p["name"]: p["side"] for p in board["halves"]["1"]["players"]}
    second = {p["name"]: p["side"] for p in board["halves"]["2"]["players"]}
    assert all(first[name] != second[name] for name in first)


def test_config_values_are_stored_in_hud_order(tmp_path):
    cfg = tmp_path / "ktp_demo.cfg"
    cfg.write_text("mp_clan_scoring_values_allies 22200\n"
                   "mp_clan_scoring_values_axis 00222\n"
                   "mp_clan_scoring_delay 15\n", encoding="utf-8")
    entry = facts.parse_config(cfg, dict(facts.BASE_DEFAULTS))
    # The config string is reversed against the HUD; flag 1 must come first.
    assert entry["tick_value_allies"] == [0, 0, 2, 2, 2]
    assert entry["tick_value_axis"] == [2, 2, 2, 0, 0]
    assert entry["scoring_delay_seconds"] == 15
    assert entry["capout_bonus_allies"] == facts.BASE_DEFAULTS["capout_bonus_allies"]


def test_commented_out_values_do_not_win(tmp_path):
    # Every map config keeps its previous values as `//` lines above the live one.
    cfg = tmp_path / "ktp_demo.cfg"
    cfg.write_text("// mp_clan_scoring_values_allies 11111\n"
                   "// mp_clan_scoring_values_axis 11111\n"
                   "mp_clan_scoring_values_allies 21120\n"
                   "mp_clan_scoring_values_axis 21021\n", encoding="utf-8")
    entry = facts.parse_config(cfg, dict(facts.BASE_DEFAULTS))
    assert entry["tick_value_allies"] == [0, 2, 1, 1, 2]


def test_curated_flag_facts_match_the_shipped_file():
    path = Path(__file__).resolve().parents[2] / "config" / "analytics" / "map_flag_facts.json"
    curated = json.loads(path.read_text(encoding="utf-8"))["maps"]
    assert curated, "the curated flag facts must not be empty"
    for map_name, entry in curated.items():
        indexes = [f["flag_index"] for f in entry["flags"]]
        assert indexes == sorted(indexes) == list(range(len(indexes))), map_name
        for flag in entry["flags"]:
            assert flag["initial_owner"] in (0, 1, 2), map_name
            assert flag["cap_points"] >= 1, map_name


def test_verify_flags_detects_a_changed_map(tmp_path, capsys):
    flags = tmp_path / "flags.json"
    flags.write_text(json.dumps({"maps": {"dod_x": {"config": "x", "flags": [
        {"flag_index": 0, "flag_name": "A", "initial_owner": 0, "cap_points": 1}]}}}),
        encoding="utf-8")
    export = tmp_path / "export.tsv"
    export.write_text("map_name\tflag_index\tflag_name\tdefault_owner\tpoints_for_cap\n"
                      "dod_x\t0\tA\t1\t1\n", encoding="utf-8")
    assert facts.verify_flags(flags, export) == 1
    assert "dod_x flag 0" in capsys.readouterr().err
