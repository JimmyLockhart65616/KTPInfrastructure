"""The opt-in enforcement-scope gate in `scripts/build-game-files-manifest.py`.

The generator reads `maps/*.res` as a manifest source. Producing those files is a FastDL
act with a different owner: a RESGen run over 33 maps on 2026-09-15 put 128 new paths into
the next regeneration, which enforced every one of them at severity "violation" because
that is the default. Nothing in the pipeline read the join — the map-bundle side prints an
entry-list delta and refuses on a failed self-check, and the side where the consequence
lands on a player had no equivalent.

The diff that reports this is advisory by ruling and is pinned next door in
`test_game_files_manifest_diff.py`. These pin the refusal layered on top of it: it is
armed with `--gate-scope`, it decides on the same diff that was just printed, and a
refusal leaves `--out` alone rather than dropping the widened file where the next run
would adopt it as a baseline.

Loaded by path with `paramiko` stubbed, the same way the scope guards next door do it.
"""

from __future__ import annotations

import importlib.util
import io
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
    spec = importlib.util.spec_from_file_location("_ktp_game_files_manifest_gate", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def entry(path, severity="violation", origin=".res", referenced_by=None, sha=None):
    e = {"path": path, "sha256": sha or "0" * 64, "size": 1, "origin": origin,
         "severity": severity, "category": "model_other"}
    if referenced_by:
        e["referenced_by"] = referenced_by
    return e


def manifest(entries, version="v0"):
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


def diff(mod, before, after):
    return mod.diff_manifests(manifest(before), manifest(after))


# ── what counts as an enforcement change ──────────────────────────────────────

def test_an_added_path_counts_as_enforced(mod):
    d = diff(mod, [entry("a")], [entry("a"), entry("b")])
    assert [e["path"] for e in mod.enforced_changes(d["added"])] == ["b"]
    assert d["removed"] == []


def test_review_severity_is_reported_but_does_not_gate(mod):
    """A review entry is captured and reported and never scores, so it is a disclosure
    change rather than an enforcement one. Reported either way; only enforced ones gate."""
    d = diff(mod, [], [entry("gfx/env/skyup.tga", severity="review")])
    assert [e["path"] for e in d["added"]] == ["gfx/env/skyup.tga"]
    assert mod.enforced_changes(d["added"]) == []


def test_a_removal_counts_too(mod):
    """A path leaving enforcement is coverage loss, and a gate watching only additions is
    blind to it in exactly the direction nobody notices."""
    d = diff(mod, [entry("a"), entry("b")], [entry("a")])
    assert [e["path"] for e in mod.enforced_changes(d["removed"])] == ["b"]


def test_a_changed_hash_is_not_a_scope_change(mod):
    """The gate is about WHICH paths are enforced. A file legitimately changing on the
    fleet tree must not need an acknowledgement, or the gate becomes noise and gets
    rubber-stamped."""
    d = diff(mod, [entry("a")], [entry("a", sha="f" * 64)])
    assert d["added"] == [] and d["removed"] == []
    assert d["rehashed"] == 1


# ── the gate's decision ───────────────────────────────────────────────────────

def test_no_change_passes_with_no_counts(mod):
    d = diff(mod, [entry("a")], [entry("a")])
    assert mod.gate_scope_change(d, None, None, out=io.StringIO()) is True


def test_unacknowledged_widening_refuses(mod):
    d = diff(mod, [], [entry("b")])
    out = io.StringIO()
    assert mod.gate_scope_change(d, None, None, out=out) is False
    assert "--accept-added 1" in out.getvalue()


def test_matching_count_accepts(mod):
    d = diff(mod, [], [entry("b"), entry("c")])
    assert mod.gate_scope_change(d, 2, None, out=io.StringIO()) is True


def test_wrong_count_refuses(mod):
    """The acknowledgement is a count so it expires. A flag that said 2 stops agreeing the
    moment the regeneration would add 3 — which is when someone needs to look again."""
    d = diff(mod, [], [entry("b"), entry("c"), entry("d")])
    out = io.StringIO()
    assert mod.gate_scope_change(d, 2, None, out=out) is False
    assert "does not match" in out.getvalue()


def test_accepting_additions_does_not_also_accept_removals(mod):
    d = diff(mod, [entry("a")], [entry("b")])
    assert mod.gate_scope_change(d, 1, None, out=io.StringIO()) is False
    assert mod.gate_scope_change(d, 1, 1, out=io.StringIO()) is True


def test_zero_is_not_a_blanket_accept(mod):
    """`--accept-added 0` against a real widening must refuse, not pass — otherwise the
    cheapest thing to paste into a runbook is the one that disables the gate."""
    d = diff(mod, [], [entry("b")])
    assert mod.gate_scope_change(d, 0, None, out=io.StringIO()) is False


# ── end to end through main() ─────────────────────────────────────────────────


class _FakeSSHClient:
    def set_missing_host_key_policy(self, *a):
        pass

    def connect(self, *a, **k):
        pass

    def close(self):
        pass


def run_main(mod, tmp_path, monkeypatch, built, argv):
    monkeypatch.setattr(mod, "build_manifest", lambda *a, **k: built["files"])
    monkeypatch.setattr(mod, "assemble_manifest", lambda *a, **k: built)
    monkeypatch.setattr(mod, "paramiko", types.SimpleNamespace(
        SSHClient=_FakeSSHClient, AutoAddPolicy=lambda: None))
    monkeypatch.setattr(sys, "argv", ["build-game-files-manifest.py",
                                      "--filelist", str(tmp_path / "ktp_file.ini"),
                                      "--ssh-password", "unused-by-the-fake-client"] + argv)
    return mod.main()


def test_widening_is_advisory_unless_the_gate_is_armed(mod, tmp_path, monkeypatch, capsys):
    """The diff refuses on no run of its own. Arming it is a separate, explicit act."""
    out = tmp_path / "m.json"
    out.write_text(json.dumps(manifest([entry("models/a.mdl")])), encoding="utf-8")

    run_main(mod, tmp_path, monkeypatch,
             manifest([entry("models/a.mdl"), entry("models/b.mdl")], version="new"),
             ["--out", str(out)])

    assert "models/b.mdl" in capsys.readouterr().err
    assert json.loads(out.read_text(encoding="utf-8"))["_meta"]["version"] == "new"


def test_armed_gate_refuses_and_leaves_the_output_untouched(mod, tmp_path, monkeypatch, capsys):
    """A refusal that still wrote --out would leave the widened manifest on disk as the
    next run's baseline, so the second run would find nothing added and pass — a refusal
    laundering itself into an approval."""
    out = tmp_path / "m.json"
    out.write_text(json.dumps(manifest([entry("models/a.mdl")], version="old")),
                   encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run_main(mod, tmp_path, monkeypatch,
                 manifest([entry("models/a.mdl"), entry("models/b.mdl")], version="new"),
                 ["--out", str(out), "--gate-scope"])

    assert exc.value.code == 2
    assert json.loads(out.read_text(encoding="utf-8"))["_meta"]["version"] == "old"
    candidate = json.loads((tmp_path / "m.json.candidate").read_text(encoding="utf-8"))
    assert candidate["_meta"]["version"] == "new", "the hash pass must not be thrown away"
    assert "REFUSED" in capsys.readouterr().err


def test_an_accept_count_arms_the_gate_on_its_own(mod, tmp_path, monkeypatch):
    """Otherwise a count could be handed to a gate that is not running, and the run would
    read as acknowledged while refusing nothing."""
    out = tmp_path / "m.json"
    out.write_text(json.dumps(manifest([entry("models/a.mdl")])), encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        run_main(mod, tmp_path, monkeypatch,
                 manifest([entry("models/a.mdl"), entry("models/b.mdl")]),
                 ["--out", str(out), "--accept-added", "99"])
    assert exc.value.code == 2


def test_the_right_count_lets_the_write_through(mod, tmp_path, monkeypatch, capsys):
    out = tmp_path / "m.json"
    out.write_text(json.dumps(manifest([entry("models/a.mdl")], version="old")),
                   encoding="utf-8")

    run_main(mod, tmp_path, monkeypatch,
             manifest([entry("models/a.mdl"), entry("models/b.mdl")], version="new"),
             ["--out", str(out), "--accept-added", "1"])

    assert json.loads(out.read_text(encoding="utf-8"))["_meta"]["version"] == "new"
    assert "accepted: 1 enforced path(s) added" in capsys.readouterr().err


def test_the_gate_decides_on_the_diff_that_was_printed(mod, tmp_path, monkeypatch, capsys):
    """The report and the refusal have to be the same comparison, or the count the
    operator is told to paste is not the count the gate will check."""
    out = tmp_path / "m.json"
    out.write_text(json.dumps(manifest([entry("models/a.mdl")])), encoding="utf-8")

    with pytest.raises(SystemExit):
        run_main(mod, tmp_path, monkeypatch,
                 manifest([entry("models/a.mdl"), entry("models/b.mdl"),
                           entry("gfx/env/sky.tga", severity="review")]),
                 ["--out", str(out), "--gate-scope"])

    err = capsys.readouterr().err
    assert "ADDED 2 paths" in err, err
    # Two paths added, one of them review-only, so the count to acknowledge is 1.
    assert "--accept-added 1" in err


def test_an_armed_gate_with_no_baseline_says_it_did_not_run(mod, tmp_path, monkeypatch, capsys):
    """Dropping the missing-baseline refusal must not let an armed gate pass silently: the
    run writes, but it may not read as an acknowledged one."""
    out = tmp_path / "fresh.json"

    run_main(mod, tmp_path, monkeypatch, manifest([entry("models/a.mdl")]),
             ["--out", str(out), "--gate-scope"])

    assert "GATE ARMED BUT NOT RUN" in capsys.readouterr().err
    assert out.exists()
