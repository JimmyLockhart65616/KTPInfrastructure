"""Advisory scope diff for `scripts/build-game-files-manifest.py`.

The generator opens its output with `"w"` and says nothing about what moved. Scope is
the set of paths the client hashes, so a regeneration run for an unrelated reason can
widen what every player is checked against and leave a changed version string as the
only trace. One did: +128 paths, unannounced. Roughly 60% of the installed manifest is
.res-derived, and an unreferenced .res sitting on the source tree enters scope the next
time anyone runs the generator for any reason at all.

These tests pin the two halves that make the print worth having:

  1. it reports the right thing — added and removed paths grouped by origin, plus the
     severity flips that widen enforcement without adding a path;
  2. it stays READABLE at the size that matters. A 128-line wall is skipped by the
     human it exists to inform, which is the same outcome as printing nothing.

And the one ordering mistake that would make it useless: the baseline is the file the
run is about to overwrite, so reading it late reports every path as added.

⛔ It is ADVISORY by operator ruling — it prints, it never refuses. Whether a
regeneration should need an acknowledgement is a separate decision, to be taken against
a real distribution of diffs rather than one historical event, so nothing here asserts
either way about a future gate.

Loaded by path with `paramiko` stubbed, the same way the scope guards next door do it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build-game-files-manifest.py"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_game_files_manifest_diff", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- fixtures


def entry(path, origin=".res", severity="violation", sha=None, maps=None, alternates=None):
    e = {
        "path": path,
        "sha256": sha or ("0" * 63 + "1"),
        "size": 1024,
        "origin": origin,
        "category": "model_other",
        "severity": severity,
    }
    if maps is not None:
        e["referenced_by"] = list(maps)
    # Absent unless curated, exactly as assemble_manifest writes it: the real manifest
    # carries no key at all on an entry with no alternate, so a comparison that only
    # handled the present-and-empty shape would miss every real transition.
    if alternates is not None:
        e["allowed_alternate_hashes"] = list(alternates)
    return e


def manifest(entries, version="baseline00000000"):
    """A manifest shaped like the real one — the tests that drive main() print the
    existing build summary, which reads most of _meta."""
    entries = list(entries)
    return {
        "_meta": {
            "version": version,
            "total_files": len(entries),
            "total_size_bytes": sum(e["size"] for e in entries),
            "stock_files": 0,
            "dead_entry_candidates": [],
            "by_category": {},
            "by_severity": {},
            "sources": {},
        },
        "files": entries,
    }


KIT = "explicit_2026-05-02_full_kit"


# ---------------------------------------------------------------- what it reports


def test_added_and_removed_are_keyed_on_path(mod):
    before = manifest([entry("models/stays.mdl"), entry("models/goes.mdl")])
    after = manifest([entry("models/stays.mdl"), entry("models/arrives.mdl")])

    d = mod.diff_manifests(before, after)

    assert [e["path"] for e in d["added"]] == ["models/arrives.mdl"]
    assert [e["path"] for e in d["removed"]] == ["models/goes.mdl"]
    assert (d["total_before"], d["total_after"]) == (2, 2)
    # A same-size diff is the case a totals-only report calls "no change".
    assert d["added"] and d["removed"]


def test_totals_before_and_after_are_reported(mod):
    before = manifest([entry(f"models/a{i}.mdl") for i in range(5)])
    after = manifest([entry(f"models/a{i}.mdl") for i in range(9)])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "5 -> 9" in text
    assert "+4" in text


def test_added_paths_are_grouped_by_origin(mod):
    before = manifest([entry("models/stays.mdl")])
    after = manifest([
        entry("models/stays.mdl"),
        entry("models/mapmodels/one.mdl", maps=["dod_kalt2"]),
        entry("models/mapmodels/two.mdl", maps=["dod_kalt2"]),
        entry("models/p_bren_l.mdl", origin=KIT),
    ])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "ADDED 3 paths, 2 origins:" in text
    assert ".res  2" in text
    assert f"{KIT}  1" in text


def test_one_origin_and_many_origins_read_differently(mod):
    """"12 new paths, all from one map" and "12 across four origins" are different
    findings, and a flat list of 12 paths does not distinguish them."""
    before = manifest([entry("models/stays.mdl")])
    one_map = manifest([entry("models/stays.mdl")] +
                       [entry(f"models/mapmodels/m{i}.mdl", maps=["dod_kalt2"]) for i in range(12)])
    four_origins = manifest([entry("models/stays.mdl")] + [
        entry(f"models/mapmodels/m{i}.mdl", maps=["dod_kalt2"]) for i in range(3)
    ] + [
        entry(f"models/p_k{i}.mdl", origin=KIT) for i in range(3)
    ] + [
        entry(f"sound/player/pl_s{i}.wav", origin="filelist.ini") for i in range(3)
    ] + [
        entry(f"models/x{i}.mdl", origin="explicit_2026-05-01") for i in range(3)
    ])

    narrow = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, one_map), "b"))
    wide = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, four_origins), "b"))

    assert "ADDED 12 paths, 1 origin:" in narrow
    assert "maps: dod_kalt2 12" in narrow
    assert "ADDED 12 paths, 4 origins:" in wide


def test_res_additions_name_their_referencing_maps(mod):
    before = manifest([])
    after = manifest([entry(f"models/mapmodels/a{i}.mdl", maps=["dod_kalt2"]) for i in range(7)] +
                     [entry("models/mapmodels/b.mdl", maps=["dod_anzio"])])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "maps: dod_kalt2 7, dod_anzio 1" in text


def test_added_severities_are_summarised_per_origin(mod):
    before = manifest([])
    after = manifest([entry("gfx/env/skyup.tga", severity="review", maps=["dod_kalt2"]),
                      entry("models/mapmodels/a.mdl", maps=["dod_kalt2"])])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "severity: review 1, violation 1" in text


def test_severity_flip_is_reported_though_no_path_moved(mod):
    """review -> violation widens enforcement without adding a single path. A diff that
    only watched path membership would call this run identical."""
    path = "gfx/env/skyup.tga"
    before = manifest([entry(path, severity="review")])
    after = manifest([entry(path, severity="violation")])

    d = mod.diff_manifests(before, after)
    text = "\n".join(mod.format_scope_diff(d, "b"))

    assert d["added"] == [] and d["removed"] == []
    assert d["severity_changed"] == [(path, "review", "violation")]
    assert f"{path}: review -> violation" in text


def test_rehashed_paths_are_counted_not_listed(mod):
    before = manifest([entry(f"models/a{i}.mdl", sha="a" * 64) for i in range(4)])
    after = manifest([entry(f"models/a{i}.mdl", sha="b" * 64) for i in range(4)])

    d = mod.diff_manifests(before, after)
    text = "\n".join(mod.format_scope_diff(d, "b"))

    assert d["rehashed"] == 4
    assert "RE-HASHED 4 paths" in text
    # Without this line a run that changed nothing but bytes prints "no change" beside a
    # version that moved, and the reader concludes the diff is broken.
    assert "no change" not in text


def test_identical_manifests_say_so(mod):
    m = manifest([entry("models/a.mdl"), entry("models/b.mdl")])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(m, m), "b"))

    assert "no change" in text
    assert "ADDED" not in text and "REMOVED" not in text


# ------------------------------------------------- the axis that reads as nothing
#
# An operator-curated `allowed_alternate_hashes` entry is what stops a legitimate
# community copy scoring. Drop one and every holder of that file becomes a violation:
# no path added, no severity moved, no hash changed. Reporting only path membership,
# severity and re-hash printed "no change: same paths, same severities, same hashes"
# over exactly that — the worst change this diff exists to catch, in reassuring words.

ALT_A = "a" * 64
ALT_B = "b" * 64
SCORE_PACK = "sound/ambience/axisscore.wav"


def test_a_dropped_alternate_is_not_no_change(mod):
    """The headline case. Nothing else about the entry moves."""
    before = manifest([entry(SCORE_PACK, alternates=[ALT_A])])
    after = manifest([entry(SCORE_PACK)])

    d = mod.diff_manifests(before, after)
    text = "\n".join(mod.format_scope_diff(d, "b"))

    assert d["added"] == [] and d["removed"] == []
    assert d["severity_changed"] == [] and d["rehashed"] == 0
    assert "no change" not in text
    assert "ALTERNATES CHANGED 1 path" in text
    assert SCORE_PACK in text


def test_the_dropped_hash_itself_is_printed(mod):
    """A count cannot be acted on. The curated set is small enough to spell out, and
    which hash left is the whole question when restoring one."""
    before = manifest([entry(SCORE_PACK, alternates=[ALT_A, ALT_B])])
    after = manifest([entry(SCORE_PACK, alternates=[ALT_B])])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert f"DROPPED  {ALT_A}" in text
    assert ALT_B not in text.split("ALTERNATES CHANGED")[1]


def test_a_drop_says_it_starts_scoring(mod):
    before = manifest([entry(SCORE_PACK, alternates=[ALT_A])])
    after = manifest([entry(SCORE_PACK)])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "now scores against every holder" in text


def test_a_gain_is_reported_and_reads_the_other_way(mod):
    """Adding an alternate narrows enforcement. Still reported — an advisory blind in
    the direction nobody notices is how coverage leaves unannounced."""
    before = manifest([entry(SCORE_PACK)])
    after = manifest([entry(SCORE_PACK, alternates=[ALT_A])])

    d = mod.diff_manifests(before, after)
    text = "\n".join(mod.format_scope_diff(d, "b"))

    assert d["alternates_changed"][0]["gained"] == [ALT_A]
    assert f"ADDED    {ALT_A}" in text
    assert "no longer scores" in text


def test_a_drop_on_a_review_path_does_not_claim_it_scores(mod):
    """`review` is captured and never reaches a verdict, so nothing starts scoring.
    Saying otherwise is the noise that gets an advisory rubber-stamped."""
    path = "gfx/env/skyup.tga"
    before = manifest([entry(path, severity="review", alternates=[ALT_A])])
    after = manifest([entry(path, severity="review")])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "ALTERNATES CHANGED 1 path" in text
    assert "now scores against every holder" not in text
    assert "captured, never scored" in text


def test_the_direction_test_reads_the_right_side_of_the_flip(mod):
    """A drop arriving WITH review -> violation is two widenings at once, and the drop
    is judged on where the path ends up. Reading severity_before here would call it
    harmless on the run where it is worst."""
    before = manifest([entry(SCORE_PACK, severity="review", alternates=[ALT_A])])
    after = manifest([entry(SCORE_PACK, severity="violation")])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "review -> violation" in text
    assert "now scores against every holder" in text


def test_an_alternate_change_is_not_double_counted_as_a_path_move(mod):
    """Computed over the intersection, like severity and re-hash. A removed path takes
    its alternates with it and is already reported as a removal."""
    before = manifest([entry("models/goes.mdl", alternates=[ALT_A])])
    after = manifest([entry("models/arrives.mdl", alternates=[ALT_B])])

    d = mod.diff_manifests(before, after)

    assert d["alternates_changed"] == []
    assert [e["path"] for e in d["removed"]] == ["models/goes.mdl"]


def test_an_unchanged_alternate_set_reports_nothing(mod):
    """Order and identity, not object equality — the generator rebuilds the list every
    run, so a diff keyed on anything but content would fire on every regeneration and
    be ignored within a week."""
    m1 = manifest([entry(SCORE_PACK, alternates=[ALT_A, ALT_B])])
    m2 = manifest([entry(SCORE_PACK, alternates=[ALT_B, ALT_A])])

    d = mod.diff_manifests(m1, m2)
    text = "\n".join(mod.format_scope_diff(d, "b"))

    assert d["alternates_changed"] == []
    assert "no change" in text


def test_the_no_change_line_claims_alternates_too(mod):
    """The line is what a reader trusts instead of looking. It may only promise what
    the diff actually compared."""
    m = manifest([entry(SCORE_PACK, alternates=[ALT_A])])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(m, m), "b"))

    assert "same allowed alternates" in text


def test_severity_section_says_the_version_will_not_move(mod):
    """_meta.version hashes (path, sha256, alternates). A severity-only regeneration
    writes a new file under the SAME version string, and every ETag check downstream
    keeps serving the old copy — so the reader must not take an unmoved version as
    evidence that nothing changed."""
    path = "gfx/env/skyup.tga"
    before = manifest([entry(path, severity="review")])
    after = manifest([entry(path, severity="violation")])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))

    assert "_meta.version does NOT move for these" in text


def test_alternates_are_never_truncated_by_diff_limit(mod):
    """--diff-limit exists because a 128-path wall gets scrolled past. The curated
    alternate set is a handful of hand-made decisions and does not have that problem,
    so a limit that hid one would hide the only detail worth reading."""
    before = manifest([entry(f"sound/s{i}.wav", alternates=[ALT_A]) for i in range(6)])
    after = manifest([entry(f"sound/s{i}.wav") for i in range(6)])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b", limit=1))

    assert "ALTERNATES CHANGED 6 paths" in text
    for i in range(6):
        assert f"sound/s{i}.wav" in text
    assert text.count(f"DROPPED  {ALT_A}") == 6


# ---------------------------------------------------------------- readable when large

BIG = 128


def _big_res_addition(mod, maps=("dod_kalt2",)):
    before = manifest([entry("models/stays.mdl")])
    after = manifest([entry("models/stays.mdl")] +
                     [entry(f"models/mapmodels/big{i:03d}.mdl", maps=maps) for i in range(BIG)])
    return mod.diff_manifests(before, after)


def test_a_128_path_addition_does_not_print_128_lines(mod):
    """The failure case that matters. A wall of 128 lines is scrolled past, and a
    warning nobody reads is the same as no warning."""
    lines = mod.format_scope_diff(_big_res_addition(mod), "b")

    assert len(lines) < 30, (
        f"{len(lines)} lines for one addition — at this length the reader skims past the "
        f"count that matters:\n" + "\n".join(lines)
    )
    listed = [l for l in lines if l.strip().startswith("models/mapmodels/big")]
    assert len(listed) == mod.DIFF_LIST_LIMIT_DEFAULT


def test_the_summary_survives_the_truncation(mod):
    """What is cut is the tail of the path list, never the numbers: the whole point is
    that the reader learns "+128, one map" without reading 128 paths."""
    text = "\n".join(mod.format_scope_diff(_big_res_addition(mod), "b"))

    assert f"ADDED {BIG} paths, 1 origin:" in text
    assert f".res  {BIG}" in text
    assert f"maps: dod_kalt2 {BIG}" in text
    assert f"severity: violation {BIG}" in text
    assert f"{BIG - mod.DIFF_LIST_LIMIT_DEFAULT} more" in text


def test_truncation_notice_names_the_way_to_see_everything(mod):
    text = "\n".join(mod.format_scope_diff(_big_res_addition(mod), "b"))

    assert "--diff-limit 0" in text


def test_diff_limit_zero_lists_every_path(mod):
    lines = mod.format_scope_diff(_big_res_addition(mod), "b", limit=0)

    listed = [l for l in lines if l.strip().startswith("models/mapmodels/big")]
    assert len(listed) == BIG
    assert not any("more (--diff-limit" in l for l in lines)


def test_many_referencing_maps_are_capped_and_counted(mod):
    """A map list is the other thing that can run long — 60 maps on one line is a wall
    of its own."""
    before = manifest([])
    after = manifest([entry(f"models/mapmodels/m{i}.mdl", maps=[f"dod_map{i:02d}"])
                      for i in range(40)])

    text = "\n".join(mod.format_scope_diff(mod.diff_manifests(before, after), "b"))
    maps_line = next(l for l in text.splitlines() if "maps:" in l)

    assert len(maps_line) < 120, maps_line
    assert f"+{40 - mod._DIFF_MAPS_NAMED} more" in maps_line


def test_removals_are_grouped_and_truncated_the_same_way(mod):
    before = manifest([entry(f"models/mapmodels/gone{i:03d}.mdl", maps=["dod_old"])
                       for i in range(BIG)])
    after = manifest([])

    lines = mod.format_scope_diff(mod.diff_manifests(before, after), "b")

    assert f"  REMOVED {BIG} paths, 1 origin:" in lines
    assert len(lines) < 30


# ---------------------------------------------------------------- baseline handling


def test_missing_baseline_is_a_sentence_not_an_error(mod, tmp_path):
    previous, reason = mod.load_previous_manifest(tmp_path / "nothing.json")

    assert previous is None
    assert "no baseline" in reason
    lines = mod.scope_diff_lines(previous, manifest([]), tmp_path / "nothing.json", reason)
    assert any("unavailable" in l for l in lines)


@pytest.mark.parametrize("body,expected", [
    ("{ not json", "could not be read"),
    ('{"_meta": {}}', "no files[]"),
    ("[]", "no files[]"),
])
def test_unusable_baseline_never_raises(mod, tmp_path, body, expected):
    """An advisory that can abort the build is a gate. Every baseline failure has to come
    back as a reason string."""
    path = tmp_path / "baseline.json"
    path.write_text(body, encoding="utf-8")

    previous, reason = mod.load_previous_manifest(path)

    assert previous is None
    assert expected in reason
    assert mod.scope_diff_lines(previous, manifest([]), path, reason)


def test_baseline_version_is_named(mod, tmp_path):
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(manifest([entry("models/a.mdl")], version="460a687a4f7ed682")),
                    encoding="utf-8")

    previous, reason = mod.load_previous_manifest(path)
    text = "\n".join(mod.scope_diff_lines(previous, manifest([entry("models/a.mdl")]),
                                          path, reason))

    assert "460a687a4f7ed682" in text


# ---------------------------------------------------------------- end to end through main()


class _FakeSSHClient:
    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, *a, **k):
        pass

    def close(self):
        pass


def test_baseline_is_read_before_the_output_is_truncated(mod, tmp_path, monkeypatch, capsys):
    """The one ordering mistake that makes the whole thing useless.

    By default the baseline IS the file being overwritten. Reading it after the
    `open(..., "w")` finds an empty file and reports every path in the manifest as
    newly added — a diff that cries wolf on every run gets ignored within a week.
    """
    out = tmp_path / "game_files_manifest.json"
    out.write_text(json.dumps(manifest([entry("models/stays.mdl"), entry("models/goes.mdl")],
                                       version="oldversion000000")), encoding="utf-8")
    built = manifest([entry("models/stays.mdl"), entry("models/arrives.mdl")],
                     version="newversion000000")

    monkeypatch.setattr(mod, "build_manifest", lambda *a, **k: built["files"])
    monkeypatch.setattr(mod, "assemble_manifest", lambda *a, **k: built)
    monkeypatch.setattr(mod, "paramiko", types.SimpleNamespace(
        SSHClient=_FakeSSHClient, AutoAddPolicy=lambda: None))
    monkeypatch.setattr(sys, "argv",
                        ["build-game-files-manifest.py", "--out", str(out),
                         "--filelist", str(tmp_path / "ktp_file.ini"),
                         "--ssh-password", "unused-by-the-fake-client"])

    mod.main()

    err = capsys.readouterr().err
    assert "ADDED 1 path," in err, err
    assert "models/arrives.mdl" in err
    assert "REMOVED 1 path," in err
    assert "models/goes.mdl" in err
    assert "2 -> 2" in err
    assert "oldversion000000" in err, "the diff must name the baseline it compared against"
    # The write still happened, and with the new manifest.
    assert json.loads(out.read_text(encoding="utf-8"))["_meta"]["version"] == "newversion000000"


def test_a_run_with_no_prior_output_still_writes(mod, tmp_path, monkeypatch, capsys):
    out = tmp_path / "fresh.json"
    built = manifest([entry("models/a.mdl")])

    monkeypatch.setattr(mod, "build_manifest", lambda *a, **k: built["files"])
    monkeypatch.setattr(mod, "assemble_manifest", lambda *a, **k: built)
    monkeypatch.setattr(mod, "paramiko", types.SimpleNamespace(
        SSHClient=_FakeSSHClient, AutoAddPolicy=lambda: None))
    monkeypatch.setattr(sys, "argv",
                        ["build-game-files-manifest.py", "--out", str(out),
                         "--filelist", str(tmp_path / "ktp_file.ini"),
                         "--ssh-password", "unused-by-the-fake-client"])

    mod.main()

    assert "unavailable" in capsys.readouterr().err
    assert out.exists()


def test_diff_against_an_explicit_baseline(mod, tmp_path, monkeypatch, capsys):
    """Regenerating to a scratch path is the normal review workflow, and it has no
    baseline of its own — --baseline points it at the installed copy."""
    installed = tmp_path / "installed.json"
    installed.write_text(json.dumps(manifest([entry("models/a.mdl")])), encoding="utf-8")
    out = tmp_path / "candidate.json"
    built = manifest([entry("models/a.mdl"), entry("models/b.mdl")])

    monkeypatch.setattr(mod, "build_manifest", lambda *a, **k: built["files"])
    monkeypatch.setattr(mod, "assemble_manifest", lambda *a, **k: built)
    monkeypatch.setattr(mod, "paramiko", types.SimpleNamespace(
        SSHClient=_FakeSSHClient, AutoAddPolicy=lambda: None))
    monkeypatch.setattr(sys, "argv",
                        ["build-game-files-manifest.py", "--out", str(out),
                         "--baseline", str(installed),
                         "--filelist", str(tmp_path / "ktp_file.ini"),
                         "--ssh-password", "unused-by-the-fake-client"])

    mod.main()

    err = capsys.readouterr().err
    assert "ADDED 1 path," in err and "models/b.mdl" in err
