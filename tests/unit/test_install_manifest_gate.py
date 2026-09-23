"""The install gate in `scripts/install-game-files-manifest.py`.

The generator cannot install anything — it writes a local JSON file and stops. What
changes what players are enforced against is the copy onto the AC API host, and until
this script that copy was a hand-run `scp` + `cp` with a backup convention and no
reader. So the acknowledgement sat one step away from the consequence, and the gate
that existed protected a step where nothing reaches a player.

These pin the parts that make moving it worth doing:

  1. it is ARMED BY DEFAULT — the opposite of the generator's opt-in gate, and for the
     opposite reason;
  2. it gates on SEVERITY, not just membership. `review` -> `violation` widens what a
     player is scored on without adding a single path, and `_meta.version` does not
     cover severity, so nothing else in the pipeline notices;
  3. an unrankable severity refuses rather than being treated as harmless;
  4. it takes the backup itself, before the write, and publishes by rename so the
     path never holds a half-written document;
  5. no baseline means REFUSE, where the generator warns and writes anyway.

Loaded by path with `paramiko` stubbed, the same way the generator's guards next door
do it.
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
SCRIPT = REPO / "scripts" / "install-game-files-manifest.py"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_install_manifest_gate", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def gen(mod):
    return mod.load_generator()


def entry(path, severity="violation", origin=".res", sha=None):
    return {"path": path, "sha256": sha or "0" * 64, "size": 1, "origin": origin,
            "severity": severity, "category": "model_other"}


def manifest(entries, version="v0"):
    entries = list(entries)
    return {
        "_meta": {"version": version, "total_files": len(entries),
                  "by_severity": {}, "by_category": {}, "sources": {}},
        "files": entries,
    }


def diff_of(gen, before, after):
    return gen.diff_manifests(manifest(before), manifest(after))


def run_gate(mod, gen, diff, **acks):
    out = io.StringIO()
    ok = mod.gate_install(diff, mod.Acknowledgements(**acks), gen.enforced_changes, out=out)
    return ok, out.getvalue()


# --------------------------------------------------------------------------
# Severity — the change a membership gate cannot see
# --------------------------------------------------------------------------

def test_review_to_violation_is_a_widening(mod):
    assert mod.classify_severity_change("review", "violation") == "widened"


def test_violation_to_review_is_a_narrowing(mod):
    assert mod.classify_severity_change("violation", "review") == "narrowed"


@pytest.mark.parametrize("before,after", [("review", "quarantine"),
                                          ("quarantine", "violation"),
                                          ("", "violation"),
                                          ("violation", None)])
def test_an_unrankable_severity_is_never_ranked_harmless(mod, before, after):
    """The trap this avoids is a `.get(sev, 0)` default.

    A severity added to the generator's policy later would arrive here, rank as the
    weakest thing there is, and every transition involving it would read as a
    narrowing or as nothing at all — the gate passing precisely on the change nobody
    has looked at yet.
    """
    assert mod.classify_severity_change(before, after) == "unknown"


def test_a_severity_flip_alone_refuses_a_membership_clean_install(mod, gen):
    """The headline case: same paths, same hashes, strictly more enforcement.

    A membership-only gate sees an empty added[] and an empty removed[] and passes.
    So does `_meta.version`, which hashes paths, hashes and alternates and not
    severity. This is the only thing in the pipeline that stops.
    """
    before = [entry("models/p_garand_l.mdl", "review")]
    after = [entry("models/p_garand_l.mdl", "violation")]
    d = diff_of(gen, before, after)

    assert d["added"] == [] and d["removed"] == []
    assert gen.enforced_changes(d["added"]) == []

    ok, text = run_gate(mod, gen, d)
    assert ok is False
    assert "--accept-widened 1" in text


def test_the_widening_count_must_match_exactly(mod, gen):
    """A count pasted out of a runbook stops agreeing the moment one more path flips."""
    before = [entry(f"models/p_{n}_l.mdl", "review") for n in ("garand", "k98s", "spring")]
    after = [entry(f"models/p_{n}_l.mdl", "violation") for n in ("garand", "k98s", "spring")]
    d = diff_of(gen, before, after)

    ok, text = run_gate(mod, gen, d, widened=2)
    assert ok is False
    assert "does not match" in text

    ok, text = run_gate(mod, gen, d, widened=3)
    assert ok is True
    assert "accepted: 3" in text


def test_a_narrowing_gates_on_its_own_flag(mod, gen):
    """Coverage loss is a decision too, and acknowledging a widening must not cover it."""
    d = diff_of(gen, [entry("gfx/env/skyup.tga", "violation")],
                [entry("gfx/env/skyup.tga", "review")])

    assert run_gate(mod, gen, d)[0] is False
    assert run_gate(mod, gen, d, widened=1)[0] is False
    assert run_gate(mod, gen, d, narrowed=1)[0] is True


def test_an_unrankable_transition_has_no_accept_flag(mod, gen):
    """There is nothing to acknowledge a count of when the direction is unknown.

    The fix is a reviewed commit teaching SEVERITY_RANK the new value, so no flag
    combination may talk past it.
    """
    d = diff_of(gen, [entry("models/p_garand.mdl", "review")],
                [entry("models/p_garand.mdl", "quarantine")])

    for acks in ({}, {"widened": 1}, {"narrowed": 1}, {"widened": 1, "narrowed": 1}):
        ok, text = run_gate(mod, gen, d, **acks)
        assert ok is False
        assert "cannot rank" in text


def test_the_verdict_classifies_rather_than_relisting_what_the_diff_printed(mod, gen):
    """The generator has already listed every flipped path under SEVERITY CHANGED. What
    it cannot say is which of them widen, and that is the only thing the gate acts on."""
    before = [entry("a.mdl", "review"), entry("b.mdl", "review"), entry("c.mdl", "violation")]
    after = [entry("a.mdl", "violation"), entry("b.mdl", "violation"), entry("c.mdl", "review")]
    text = "\n".join(mod.format_severity_verdict(
        mod.severity_transitions(diff_of(gen, before, after))))

    assert "WIDENS" in text and "2" in text
    assert "NARROWS" in text
    assert "a.mdl" not in text, "paths were already printed once; this classifies them"


def test_an_unrankable_severity_is_named_path_by_path(mod, gen):
    """It refuses and no flag covers it, so the reader has to go and look at the paths."""
    d = diff_of(gen, [entry("a.mdl", "review")], [entry("a.mdl", "quarantine")])
    text = "\n".join(mod.format_severity_verdict(mod.severity_transitions(d)))
    assert "UNRECOGNISED" in text and "a.mdl" in text


def test_no_severity_movement_prints_no_section(mod, gen):
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl", sha="1" * 64)])
    assert mod.format_severity_verdict(mod.severity_transitions(d)) == []


def test_severity_buckets_never_double_count_a_membership_change(mod, gen):
    """`severity_changed` is computed over paths on both sides, so a path cannot be
    counted once as added and again as widened."""
    d = diff_of(gen,
                [entry("a.mdl", "review")],
                [entry("a.mdl", "violation"), entry("b.mdl", "violation")])
    buckets = mod.severity_transitions(d)
    assert [p for p, _, _ in buckets["widened"]] == ["a.mdl"]
    assert [e["path"] for e in d["added"]] == ["b.mdl"]


# --------------------------------------------------------------------------
# Membership — parity with the generator's gate
# --------------------------------------------------------------------------

def test_membership_changes_still_gate_with_their_own_counts(mod, gen):
    d = diff_of(gen, [entry("a.mdl"), entry("b.mdl")], [entry("a.mdl"), entry("c.mdl")])

    assert run_gate(mod, gen, d)[0] is False
    assert run_gate(mod, gen, d, added=1)[0] is False          # removal unacknowledged
    assert run_gate(mod, gen, d, added=1, removed=1)[0] is True


def test_an_added_review_path_does_not_gate(mod, gen):
    """A `review` entry is captured and never scores, so adding one changes what is
    disclosed rather than what is enforced. It is printed; it does not refuse."""
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl"), entry("gfx/env/skyup.tga", "review")])
    ok, text = run_gate(mod, gen, d)
    assert ok is True
    assert "nothing enforced entered or left scope" in text


def test_a_count_for_a_change_that_has_since_vanished_refuses(mod, gen):
    """`--accept-added 14` against a diff that now adds nothing is the same staleness as
    a count that is too low: the manifest moved between reading it and installing it."""
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl")])
    ok, text = run_gate(mod, gen, d, added=14)
    assert ok is False
    assert "does not match the 0" in text


def test_a_clean_diff_passes_and_says_so(mod, gen):
    d = diff_of(gen, [entry("a.mdl")], [entry("a.mdl", sha="1" * 64)])
    ok, text = run_gate(mod, gen, d)
    assert ok is True
    assert "no severity moved" in text or "nothing enforced entered" in text


def test_added_and_removed_cannot_cancel_out(mod, gen):
    """Four independent counts rather than one total: an addition and a removal in the
    same run are two decisions, and a single net figure would net them to nothing."""
    d = diff_of(gen, [entry("a.mdl")], [entry("b.mdl")])
    assert len(gen.enforced_changes(d["added"])) == 1
    assert len(gen.enforced_changes(d["removed"])) == 1
    assert run_gate(mod, gen, d, added=1)[0] is False
    assert run_gate(mod, gen, d, removed=1)[0] is False


# --------------------------------------------------------------------------
# Backup naming
# --------------------------------------------------------------------------

def test_backup_sits_beside_the_manifest_and_is_readable_in_an_ls(mod):
    from datetime import datetime, timezone
    when = datetime(2026, 9, 23, tzinfo=timezone.utc)
    name = mod.backup_name("/opt/ktp-ac-api/game_files_manifest.json", "pre-weapon-kit", when)
    assert name == "/opt/ktp-ac-api/game_files_manifest.json.bak-pre-weapon-kit-20260923"


def test_a_second_install_the_same_day_does_not_overwrite_the_first_backup(mod):
    """The collision would replace the only copy of what was live this morning with a
    copy of what has been live since lunchtime — the rollback target becoming the thing
    you are rolling back from."""
    from datetime import datetime, timezone
    when = datetime(2026, 9, 23, 14, 5, 9, tzinfo=timezone.utc)
    first = mod.backup_name("/opt/ktp-ac-api/m.json", "fix", when)
    second = mod.backup_name("/opt/ktp-ac-api/m.json", "fix", when, taken={first})

    assert second != first
    assert second.endswith("-140509")


def test_backup_collision_scan_ignores_the_manifest_neighbours(mod):
    """`uploads/` is the evidence corpus and `releases/` holds a client binary. The one
    call that reads this directory must not be able to return either."""
    class Dir:
        def listdir(self, path):
            return ["m.json", "m.json.bak-old-20260101", "uploads", "releases", "appsettings.json"]

    found = mod.existing_backup_names(Dir(), "/opt/ktp-ac-api/m.json")
    assert found == {"/opt/ktp-ac-api/m.json.bak-old-20260101"}


def test_an_unlistable_directory_does_not_stop_the_install(mod):
    class Denied:
        def listdir(self, path):
            raise OSError("permission denied")

    assert mod.existing_backup_names(Denied(), "/opt/ktp-ac-api/m.json") == set()


def test_a_reason_cannot_steer_the_backup_out_of_the_directory(mod):
    """`--reason` reaches a path, and a slash in it would write the backup somewhere
    other than beside the manifest — including on top of something else."""
    name = mod.backup_name("/opt/ktp-ac-api/m.json", "../../etc/cron.d/oops")
    assert "/etc/" not in name
    assert name.startswith("/opt/ktp-ac-api/m.json.bak-")


# --------------------------------------------------------------------------
# The copy itself
# --------------------------------------------------------------------------

class FakeFile(io.BytesIO):
    def __init__(self, store, path, mode):
        super().__init__(store.get(path, b"") if "r" in mode else b"")
        self._store, self._path, self._mode = store, path, mode

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if "w" in self._mode:
            self._store[self._path] = self.getvalue()
        self.close()
        return False


class FakeSFTP:
    """Just enough SFTP to watch the order of operations."""

    def __init__(self, files=None, fail_on_write=None):
        self.files = dict(files or {})
        self.log = []
        self.fail_on_write = fail_on_write

    def open(self, path, mode="r"):
        if "w" in mode:
            if self.fail_on_write and self.fail_on_write in path:
                raise OSError("disk full")
            self.log.append(("write", path))
        else:
            if path not in self.files:
                raise OSError(f"No such file: {path}")
            self.log.append(("read", path))
        return FakeFile(self.files, path, mode)

    def chmod(self, path, mode):
        self.log.append(("chmod", path, mode))

    def posix_rename(self, src, dst):
        self.log.append(("rename", src, dst))
        self.files[dst] = self.files.pop(src)

    def remove(self, path):
        self.log.append(("remove", path))
        self.files.pop(path, None)

    def listdir(self, path):
        self.log.append(("listdir", path))
        prefix = path.rstrip("/") + "/"
        return [p[len(prefix):] for p in self.files if p.startswith(prefix)]


LIVE = "/opt/ktp-ac-api/game_files_manifest.json"


def test_the_backup_is_taken_before_the_write(mod):
    """Not a convention someone remembers: the copy that preserves the rollback happens
    in the same call that replaces the file."""
    sftp = FakeSFTP({LIVE: b'{"files": []}'})
    backup = mod.install(sftp, LIVE, b'{"files": [1]}', "pre-weapon-kit",
                         had_previous=True, out=io.StringIO())

    assert sftp.files[backup] == b'{"files": []}'
    assert sftp.files[LIVE] == b'{"files": [1]}'
    writes = [i for i, ev in enumerate(sftp.log) if ev[0] == "write"]
    assert sftp.log[writes[0]][1] == backup, "the backup must be the first thing written"


def test_the_live_path_is_never_opened_for_writing(mod):
    """The API caches on mtime alone and serves whatever bytes are there, so a partial
    write is served as gospel. Staging beside the target and renaming means the path
    only ever holds a complete document."""
    sftp = FakeSFTP({LIVE: b'{"files": []}'})
    mod.install(sftp, LIVE, b'{"files": [1]}', "r", had_previous=True, out=io.StringIO())

    assert ("write", LIVE) not in sftp.log
    assert ("rename", LIVE + ".installing", LIVE) in sftp.log


def test_every_mutating_operation_stays_on_the_manifests_own_name(mod):
    """`/opt/ktp-ac-api/` also holds `uploads/` — the evidence corpus — and `releases/`.

    The one call that names the directory is a `listdir`, which reads names to avoid a
    backup collision. Everything that writes, renames or removes must be the manifest
    or a name derived from it, so the two are asserted apart rather than together.
    """
    sftp = FakeSFTP({LIVE: b'{"files": []}'})
    mod.install(sftp, LIVE, b'{"files": [1]}', "r", had_previous=True, out=io.StringIO())

    mutating = [ev for ev in sftp.log if ev[0] in ("write", "rename", "remove", "chmod")]
    assert mutating, "the fake recorded nothing — this would pass without the code running"
    for event in mutating:
        for arg in event[1:]:
            if isinstance(arg, str):
                assert arg.startswith(LIVE), f"{event} escaped the manifest path"

    directory_ops = [ev for ev in sftp.log if ev[0] == "listdir"]
    assert [ev[0] for ev in directory_ops] == ["listdir"], \
        "a directory was operated on by something other than a name-listing read"


def test_a_failed_stage_removes_itself_and_leaves_the_live_file_alone(mod):
    sftp = FakeSFTP({LIVE: b'{"files": []}'}, fail_on_write=".installing")
    with pytest.raises(OSError):
        mod.install(sftp, LIVE, b"x", "r", had_previous=True, out=io.StringIO())

    assert sftp.files[LIVE] == b'{"files": []}'
    assert LIVE + ".installing" not in sftp.files


def test_a_first_install_takes_no_backup_of_nothing(mod):
    sftp = FakeSFTP({})
    assert mod.install(sftp, LIVE, b"x", "r", had_previous=False, out=io.StringIO()) is None
    assert sftp.files[LIVE] == b"x"


def test_bytes_that_do_not_land_are_an_error_naming_the_rollback(mod):
    sftp = FakeSFTP({LIVE: b'{"files": []}'})

    real_rename = sftp.posix_rename

    def corrupting_rename(src, dst):
        real_rename(src, dst)
        sftp.files[dst] = b"truncated"

    sftp.posix_rename = corrupting_rename
    with pytest.raises(RuntimeError, match="restore"):
        mod.install(sftp, LIVE, b'{"files": [1]}', "r", had_previous=True, out=io.StringIO())


# --------------------------------------------------------------------------
# main() — arming, and what happens with nothing to compare against
# --------------------------------------------------------------------------

class FakeSSH:
    def __init__(self, sftp, config_value=""):
        self._sftp, self._config = sftp, config_value

    def open_sftp(self):
        return self._sftp

    def exec_command(self, cmd, **kw):
        return None, io.BytesIO(self._config.encode()), io.BytesIO(b"")

    def close(self):
        pass


def run_main(mod, monkeypatch, tmp_path, sftp, argv, config_value=""):
    monkeypatch.setattr(mod, "connect", lambda *a, **k: FakeSSH(sftp, config_value))
    return mod.main(argv)


def write_candidate(tmp_path, entries):
    p = tmp_path / "candidate.json"
    p.write_text(json.dumps(manifest(entries)), encoding="utf-8")
    return str(p)


BASE_ARGS = ["--server", "example.invalid", "--reason", "test"]


def test_the_gate_is_armed_without_asking(mod, monkeypatch, tmp_path, capsys):
    """No `--gate-scope` equivalent. Every run of this script changes what players are
    checked against, so the acknowledgement is the default rather than a flag."""
    sftp = FakeSFTP({LIVE: json.dumps(manifest([entry("a.mdl", "review")])).encode()})
    candidate = write_candidate(tmp_path, [entry("a.mdl", "violation")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 2
    assert "--accept-widened 1" in capsys.readouterr().err
    assert sftp.files[LIVE] == json.dumps(manifest([entry("a.mdl", "review")])).encode()


def test_no_baseline_refuses_rather_than_installing_unexamined(mod, monkeypatch, tmp_path, capsys):
    """The generator prints GATE ARMED BUT NOT RUN and writes anyway, which is right
    for a local file nobody is served. Here the same situation would put an unreviewed
    manifest in front of every player, so "could not compare" must not read as "passed"."""
    sftp = FakeSFTP({})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 2
    assert "no installed manifest to compare against" in capsys.readouterr().err
    assert LIVE not in sftp.files


def test_an_unparseable_installed_file_is_still_backed_up(mod, monkeypatch, tmp_path):
    """"Is there a baseline to gate against?" and "is there a file I am about to
    destroy?" are different questions. Answering the second with the first means a
    truncated manifest — the file you would most want back — is overwritten with no copy.
    """
    sftp = FakeSFTP({LIVE: b'{"files": [ tru'})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE, "--no-gate"])

    assert rc == 0
    backups = [p for p in sftp.files if p.startswith(LIVE + ".bak-")]
    assert len(backups) == 1
    assert sftp.files[backups[0]] == b'{"files": [ tru'


def test_an_unparseable_installed_file_still_refuses_when_gated(mod, monkeypatch, tmp_path, capsys):
    """It cannot be diffed, so it is not a baseline — backing it up does not make it one."""
    sftp = FakeSFTP({LIVE: b"not json"})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 2
    assert "not valid JSON" in capsys.readouterr().err
    assert sftp.files[LIVE] == b"not json"


def test_no_gate_is_the_break_glass_and_announces_itself(mod, monkeypatch, tmp_path, capsys):
    sftp = FakeSFTP({})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE, "--no-gate"])

    assert rc == 0
    assert "GATE DISARMED" in capsys.readouterr().err
    assert LIVE in sftp.files


def test_no_gate_with_an_accept_count_is_refused_as_contradictory(mod, monkeypatch, tmp_path):
    sftp = FakeSFTP({})
    candidate = write_candidate(tmp_path, [entry("a.mdl")])

    with pytest.raises(SystemExit) as exc:
        run_main(mod, monkeypatch, tmp_path, sftp,
                 BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                              "--no-gate", "--accept-added", "1"])
    assert "contradictory" in str(exc.value)


def test_an_acknowledged_install_goes_through_and_backs_itself_up(mod, monkeypatch, tmp_path, capsys):
    sftp = FakeSFTP({LIVE: json.dumps(manifest([entry("a.mdl", "review")])).encode()})
    candidate = write_candidate(tmp_path, [entry("a.mdl", "violation")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                               "--accept-widened", "1"])

    assert rc == 0
    assert json.loads(sftp.files[LIVE])["files"][0]["severity"] == "violation"
    assert any(p.startswith(LIVE + ".bak-") for p in sftp.files)
    assert "rollback:" in capsys.readouterr().err


def test_dry_run_reports_the_verdict_and_writes_nothing(mod, monkeypatch, tmp_path, capsys):
    original = json.dumps(manifest([entry("a.mdl", "review")])).encode()
    sftp = FakeSFTP({LIVE: original})
    candidate = write_candidate(tmp_path, [entry("a.mdl", "violation")])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE,
                               "--accept-widened", "1", "--dry-run"])

    assert rc == 0
    assert sftp.files[LIVE] == original
    assert not any(p.startswith(LIVE + ".bak-") for p in sftp.files)
    assert "stopping before the copy" in capsys.readouterr().err


def test_an_identical_manifest_is_not_reinstalled(mod, monkeypatch, tmp_path, capsys):
    """Re-installing the same bytes would back a file up against its own twin and move
    the mtime the API's cache is keyed on, for no change at all."""
    candidate = write_candidate(tmp_path, [entry("a.mdl")])
    sftp = FakeSFTP({LIVE: Path(candidate).read_bytes()})

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate, "--installed-path", LIVE])

    assert rc == 0
    assert "byte-identical" in capsys.readouterr().err
    assert not any(p.startswith(LIVE + ".bak-") for p in sftp.files)


def test_the_installed_path_comes_from_the_api_config(mod, monkeypatch, tmp_path, capsys):
    """A manifest installed at the documented path while the API reads another one is an
    install that changed nothing and reported success."""
    elsewhere = "/srv/ac/manifest.json"
    sftp = FakeSFTP({elsewhere: json.dumps(manifest([entry("a.mdl")])).encode()})
    candidate = write_candidate(tmp_path, [entry("a.mdl", sha="1" * 64)])

    rc = run_main(mod, monkeypatch, tmp_path, sftp,
                  BASE_ARGS + ["--manifest", candidate], config_value=elsewhere)

    assert rc == 0
    assert json.loads(sftp.files[elsewhere])["files"][0]["sha256"] == "1" * 64
    assert "NOT the default" in capsys.readouterr().err


def test_a_host_must_be_named(mod, monkeypatch, tmp_path):
    monkeypatch.delenv("KTP_AC_API_HOST", raising=False)
    candidate = write_candidate(tmp_path, [entry("a.mdl")])
    with pytest.raises(SystemExit) as exc:
        mod.main(["--manifest", candidate, "--reason", "test"])
    assert "--server is required" in str(exc.value)
