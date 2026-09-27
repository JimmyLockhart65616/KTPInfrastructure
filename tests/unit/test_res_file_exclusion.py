"""`maps/*.res` leaves manifest scope: the server sends the list, so the client's copy
is not evidence of anything.

A `.res` that names itself becomes a downloadable resource, so FastDL hands it to every
player who joins that map and the generator then hashes it like any other asset. Two of
them were in the installed manifest. Both were rewritten on the source tree on
2026-09-16 without a regeneration behind it, which is the ordinary case rather than the
exception -- a `.res` is rewritten whenever a map is redeployed.

That combination is the defect. Every player still holding the copy FastDL gave them
last month matches the old bytes and is clean; the moment the manifest is regenerated
the expected hash moves and each of them becomes a `violation` that counts toward a
verdict. GoldSrc does not re-download a file the client already has, so it does not heal
-- and no gate refuses on it, because a changed hash on a path already in scope is
printed and not gated (docs/runbooks/AC_GAME_FILES_MANIFEST.md).

Nothing is lost by excluding it. The server builds the authoritative resource list and
sends it; a player editing their local copy of a text list of filenames changes neither
what they render nor what the server enforces.

Loaded by path with `paramiko` stubbed, the same way the scope guards next door do it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build-game-files-manifest.py"

DOD = "/srv/dod"

# The map's real asset. It must stay in scope: excluding the resource list must not
# exclude what the resource list is for.
MAP_ASSET = "models/mapmodels/anjou_bakery.mdl"
# A stock path via ktp_file.ini, so the assembled manifest is not made only of .res.
FILELIST_PATH = "sound/player/pl_step1.wav"

# The self-reference. This is the shape that put a .res in the manifest at all.
SELF_REF = "maps/dod_anjou.res"
SELF_REF_UPPER = "maps/DOD_ORANGE.RES"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_manifest_res_exclusion", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Out:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


class FakeSSH:
    def __init__(self, res_files, files):
        self._res_files = res_files
        self._files = files
        self.hashed = []

    def exec_command(self, cmd, timeout=None):
        if cmd.startswith("ls "):
            return None, _Out("\n".join(f"{DOD}/maps/{n}.res" for n in self._res_files)), None
        if cmd.startswith("cat "):
            name = cmd.split("/")[-1].rstrip("'").replace(".res", "")
            return None, _Out("\n".join(self._res_files[name])), None
        if cmd.startswith("sha256sum "):
            rel = cmd.split("'")[1][len(DOD) + 1:]
            self.hashed.append(rel)
            if rel not in self._files:
                return None, _Out(""), None
            body = self._files[rel]
            sha = hashlib.sha256(body.encode()).hexdigest()
            return None, _Out(f"{sha}  {DOD}/{rel}\n{len(body)}\n"), None
        raise AssertionError(f"unexpected command: {cmd}")


REFERENCED = [MAP_ASSET, SELF_REF, SELF_REF_UPPER]


@pytest.fixture
def built(mod, tmp_path):
    ini = tmp_path / "ktp_file.ini"
    ini.write_text("// header\n" + FILELIST_PATH[len("sound/"):] + "\n")
    on_disk = {p.lower(): f"bytes-of-{p}" for p in REFERENCED}
    on_disk[FILELIST_PATH] = "bytes-of-footsteps"
    ssh = FakeSSH({"dod_anjou": REFERENCED}, on_disk)
    entries = mod.build_manifest(ssh, DOD, str(ini))
    return mod.assemble_manifest(entries, "fake", DOD), ssh


def test_the_fixture_actually_references_a_res_file(built):
    """Negative control on the fixture, not on the code.

    Every assertion below is of the form "no .res in the output". All of them pass
    against a fixture that never fed one in, so this is what makes the rest mean
    something.
    """
    manifest, _ = built
    assert any(p.lower().endswith(".res") for p in REFERENCED), (
        "the fixture feeds no .res, so the exclusion assertions cannot fail"
    )
    assert manifest["files"], "the fixture produced an empty manifest"


def test_a_self_referencing_res_is_not_a_manifest_entry(built):
    manifest, _ = built
    paths = {e["path"] for e in manifest["files"]}
    assert SELF_REF not in paths, (
        f"{SELF_REF} is in scope. FastDL serves it, so every player who has played the "
        f"map holds a copy — and its hash moves on every map redeploy, turning each of "
        f"them into a violation that does not heal"
    )


def test_the_exclusion_is_case_insensitive(built):
    """The source tree holds lower-cased names and a .res may name itself in any case.

    A case-sensitive check leaves the upper-case spelling in scope, which is the same
    defect wearing different bytes.
    """
    manifest, _ = built
    offenders = [e["path"] for e in manifest["files"] if e["path"].lower().endswith(".res")]
    assert not offenders, f"case-sensitive exclusion let these through: {offenders}"


def test_the_maps_own_assets_stay_in_scope(built):
    """The exclusion must drop the list, not what the list is for."""
    manifest, _ = built
    paths = {e["path"] for e in manifest["files"]}
    assert MAP_ASSET in paths, (
        "excluding .res dropped the map asset it references — that is a real loss of "
        "enforcement, not the intended change"
    )
    assert FILELIST_PATH in paths, "ktp_file.ini route collaterally dropped"


def test_an_excluded_res_is_never_hashed(built):
    """Excluded before the hash, not filtered after it.

    Hashing then discarding costs an SSH round trip per file on a production game host
    and reads, in the run's own counters, as work that mattered.
    """
    _, ssh = built
    hashed_res = [p for p in ssh.hashed if p.lower().endswith(".res")]
    assert not hashed_res, f"hashed a path it then excluded: {hashed_res}"


def test_the_artifact_says_res_is_excluded(built):
    """The question gets asked of the manifest months later, not of this test."""
    manifest, _ = built
    buckets = " ".join(manifest["_meta"]["excluded_buckets"]).lower()
    assert ".res" in buckets, (
        "_meta.excluded_buckets does not mention .res — a reader comparing the manifest "
        "against a map's FastDL listing finds the gap and no reason for it"
    )


def test_exclusion_is_declared_as_policy_not_buried_in_a_branch(mod):
    """A named constant is what the next reader greps for, and what a rule can be added
    to without finding the one predicate that implements it."""
    assert hasattr(mod, "EXCLUDED_EXTENSIONS"), (
        "no EXCLUDED_EXTENSIONS constant: the rule is inlined somewhere and the next "
        "extension gets added to a different place"
    )
    assert ".res" in mod.EXCLUDED_EXTENSIONS
    assert all(e.startswith(".") for e in mod.EXCLUDED_EXTENSIONS), (
        "entries must be suffixes with the dot, since endswith() is what consumes them"
    )
