"""The enforcement-scope gate in `scripts/build-game-files-manifest.py`.

The generator reads `maps/*.res` as a manifest source. Producing those files is a FastDL
act with a different owner: a RESGen run over 33 maps on 2026-09-15 put 128 new paths into
the next regeneration, which enforced every one of them at severity "violation" because
that is the default. Nothing in the pipeline read the join — the map-bundle side prints an
entry-list delta and refuses on a failed self-check, and the side where the consequence
lands on a player had no equivalent.

These pin the gate's behaviour, and in particular the three ways a gate like this fails
open: an unreadable baseline read as "nothing to compare", a missing baseline skipped
silently, and a refusal that still leaves the widened file on disk for the next run to
adopt as its baseline.

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


def entry(path, severity="violation", origin=".res", referenced_by=None):
    e = {"path": path, "sha256": "0" * 64, "size": 1, "origin": origin, "severity": severity,
         "category": "model"}
    if referenced_by:
        e["referenced_by"] = referenced_by
    return e


def write_manifest(tmp_path, name, entries):
    p = tmp_path / name
    p.write_text(json.dumps({"_meta": {"version": "x"}, "files": entries}), encoding="utf-8")
    return p


# ── reading a baseline ────────────────────────────────────────────────────────

def test_baseline_loads_by_path(mod, tmp_path):
    p = write_manifest(tmp_path, "m.json", [entry("models/p_garand.mdl")])
    assert list(mod.load_baseline_paths(p)) == ["models/p_garand.mdl"]


def test_malformed_baseline_raises_rather_than_reading_as_empty(mod, tmp_path):
    """The failure that would make every path an addition — and, once acknowledged, would
    re-baseline the whole manifest as if it had just been reviewed."""
    p = tmp_path / "broken.json"
    p.write_text('{"_meta": {}}', encoding="utf-8")
    with pytest.raises(ValueError):
        mod.load_baseline_paths(p)


def test_unparseable_baseline_raises(mod, tmp_path):
    p = tmp_path / "junk.json"
    p.write_text("not json at all", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        mod.load_baseline_paths(p)


# ── what counts as a scope change ─────────────────────────────────────────────

def test_added_path_is_reported_as_enforced(mod):
    d = mod.scope_delta({"a": entry("a")}, [entry("a"), entry("b")])
    assert d["added"] == ["b"]
    assert d["added_enforced"] == ["b"]
    assert d["removed"] == []


def test_review_severity_is_added_but_not_enforced(mod):
    """A review entry is captured and reported and never scores, so it is a disclosure
    change rather than an enforcement one. Reported either way; only enforced ones gate."""
    d = mod.scope_delta({}, [entry("gfx/env/skyup.tga", severity="review")])
    assert d["added"] == ["gfx/env/skyup.tga"]
    assert d["added_enforced"] == []


def test_removal_is_detected_too(mod):
    """A path leaving enforcement is coverage loss, and a gate watching only additions is
    blind to it in exactly the direction nobody notices."""
    d = mod.scope_delta({"a": entry("a"), "b": entry("b")}, [entry("a")])
    assert d["removed_enforced"] == ["b"]


def test_a_changed_hash_is_not_a_scope_change(mod):
    """The gate is about WHICH paths are enforced. A file legitimately changing on the
    fleet tree must not need an acknowledgement, or the gate becomes noise and gets
    rubber-stamped."""
    before = {"a": entry("a")}
    after = [dict(entry("a"), sha256="f" * 64)]
    d = mod.scope_delta(before, after)
    assert d["added"] == [] and d["removed"] == []


# ── the gate's decision ───────────────────────────────────────────────────────

def test_no_change_passes_with_no_flags(mod):
    d = mod.scope_delta({"a": entry("a")}, [entry("a")])
    assert mod.gate_scope_change(d, None, None, out=io.StringIO()) is True


def test_unacknowledged_widening_refuses(mod):
    d = mod.scope_delta({}, [entry("b")])
    out = io.StringIO()
    assert mod.gate_scope_change(d, None, None, out=out) is False
    assert "--accept-added 1" in out.getvalue()


def test_matching_count_accepts(mod):
    d = mod.scope_delta({}, [entry("b"), entry("c")])
    assert mod.gate_scope_change(d, 2, None, out=io.StringIO()) is True


def test_wrong_count_refuses(mod):
    """The acknowledgement is a count so it expires. A flag that said 2 stops agreeing the
    moment the regeneration would add 3 — which is when someone needs to look again."""
    d = mod.scope_delta({}, [entry("b"), entry("c"), entry("d")])
    out = io.StringIO()
    assert mod.gate_scope_change(d, 2, None, out=out) is False
    assert "does not match" in out.getvalue()


def test_accepting_additions_does_not_also_accept_removals(mod):
    d = mod.scope_delta({"a": entry("a")}, [entry("b")])
    assert mod.gate_scope_change(d, 1, None, out=io.StringIO()) is False
    assert mod.gate_scope_change(d, 1, 1, out=io.StringIO()) is True


def test_zero_is_not_a_blanket_accept(mod):
    """`--accept-added 0` against a real widening must refuse, not pass — otherwise the
    cheapest thing to paste into a runbook is the one that disables the gate."""
    d = mod.scope_delta({}, [entry("b")])
    assert mod.gate_scope_change(d, 0, None, out=io.StringIO()) is False


# ── the report a human actually reads ─────────────────────────────────────────

def test_delta_report_names_the_map_that_pulled_a_path_in(mod):
    d = mod.scope_delta({}, [entry("models/x.mdl", referenced_by=["dod_armory_b7"])])
    out = io.StringIO()
    mod.print_scope_delta(d, out=out)
    text = out.getvalue()
    assert "origin=.res" in text
    assert "dod_armory_b7" in text
    assert "[violation] models/x.mdl" in text


def test_delta_report_says_so_when_nothing_changed(mod):
    out = io.StringIO()
    mod.print_scope_delta(mod.scope_delta({"a": entry("a")}, [entry("a")]), out=out)
    assert "no paths added or removed" in out.getvalue()
