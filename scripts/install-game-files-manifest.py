#!/usr/bin/env python3
"""Install a built game-files manifest onto the AC API host, gated.

`build-game-files-manifest.py` installs nothing. It writes a JSON file where you
point `--out` and stops; nothing reaches a player until someone copies that file
into place on the data server. That copy was a hand-run `scp` + `cp` pair, and it
is the step where enforcement actually changes for every player with the client
installed. This is that step, with the acknowledgement attached to it.

What it does, in order:

  1. resolves the installed manifest path from the API's own configuration, so the
     gate compares against — and later replaces — the file the API is really serving;
  2. downloads it and prints a scope diff of what the install would change, rendered
     by the generator's own `format_scope_diff` so the two steps describe a change
     the same way;
  3. refuses, unless every enforced change is acknowledged by an exact count;
  4. takes the backup itself;
  5. writes atomically and verifies the bytes that landed.

⚠️ The gate is ARMED BY DEFAULT — that is the whole point of moving it here.
The generator's `--gate-scope` is opt-in because a regeneration reaches nobody:
arming it by default would be friction where nothing happens to a player. Here
the opposite holds. Every run of this script changes what players are checked
against, so the acknowledgement belongs on by default and `--no-gate` is the
break-glass, not the workflow.

🔴 Severity is gated, not just membership. `review` -> `violation` widens
enforcement without adding a single path: the file was already hashed and already
reported, and the flip is what makes a mismatch score against the player. A
membership-only gate is blind to it, and so is `_meta.version` — that hash covers
paths, hashes and allowed alternates, so a severity-only change leaves the version
string untouched and every version-based identity check agrees that nothing moved.
It has happened: six lowered weapon models (`p_*_l.mdl`) went review -> violation
between the 2026-05-07 manifest and the installed one.

⛔ This writes exactly one file. `/opt/ktp-ac-api/` also holds `uploads/`, the
evidence corpus, and `releases/`, a client binary copy — so nothing here operates
on a directory, and the temporary file it stages is named and removed by path.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import paramiko

# Remote-writing entry point: refuse to run from a checkout behind origin/main
# (ktp_script_freshness.py). The failure mode is this script's own reason for
# existing — a copy predating the severity gate would install a widening and
# report success, because a check it has never heard of cannot decline.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ktp_script_freshness import require_current  # noqa: E402


# Where the API looks when `GameFilesManifestPath` is unset — the default in
# KTPAntiCheat.Api/Program.cs. Used only as the fallback for --installed-path;
# the configured value wins, because a manifest installed at the documented path
# while the API reads another one is an install that changed nothing.
DEFAULT_MANIFEST_PATH = "/opt/ktp-ac-api/game_files_manifest.json"
DEFAULT_APPSETTINGS = "/opt/ktp-ac-api/appsettings.json"

# Enforcement strength, weakest first. A move UP this list widens what a player is
# scored on; a move DOWN narrows it. `review` is captured, reported and shown to an
# admin, and never reaches a verdict; `violation` counts.
#
# Deliberately not a dict lookup with a default: an unrecognised severity must not
# be ranked as harmless. See `classify_severity_change`.
SEVERITY_RANK = {"review": 0, "violation": 1}


# --------------------------------------------------------------------------
# Generator reuse
# --------------------------------------------------------------------------

def load_generator(script_dir=None):
    """The generator module, loaded by path because its filename has hyphens.

    The diff and its rendering live there and are pinned by
    `tests/unit/test_game_files_manifest_diff.py`. Importing them is what keeps the
    two steps from growing separate vocabularies for the same change — an operator
    who has read one diff should not have to learn a second layout to read this one.
    """
    script_dir = Path(script_dir or Path(__file__).resolve().parent)
    src = script_dir / "build-game-files-manifest.py"
    if not src.exists():
        raise FileNotFoundError(
            f"{src} not found. This script reuses the generator's scope diff, so the two "
            "travel together. Take both:\n"
            "  git archive origin/main scripts/install-game-files-manifest.py "
            "scripts/build-game-files-manifest.py | tar -x -C <workdir>"
        )
    spec = importlib.util.spec_from_file_location("_ktp_game_files_manifest", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# Severity gate — the change a membership gate cannot see
# --------------------------------------------------------------------------

def classify_severity_change(before, after):
    """'widened', 'narrowed' or 'unknown' for one severity transition.

    `unknown` covers any severity this script has no rank for, in either direction,
    and it gates. A severity added to the generator's policy later would otherwise
    arrive here and be silently ranked as harmless by a `.get(s, 0)` — the gate would
    keep passing while the meaning of the change was exactly what nobody had looked at.
    Failing closed on a string we do not understand costs one refusal and one commit.
    """
    if before not in SEVERITY_RANK or after not in SEVERITY_RANK:
        return "unknown"
    if SEVERITY_RANK[after] > SEVERITY_RANK[before]:
        return "widened"
    if SEVERITY_RANK[after] < SEVERITY_RANK[before]:
        return "narrowed"
    return None  # equal ranks, different spellings — nothing to decide


def severity_transitions(diff):
    """Group the diff's severity flips into the three buckets the gate counts.

    Reads `diff["severity_changed"]`, which the generator computes over paths present
    on BOTH sides. So these never overlap with added/removed, and a path cannot be
    counted twice by two halves of the same gate.
    """
    buckets = {"widened": [], "narrowed": [], "unknown": []}
    for path, before, after in diff.get("severity_changed", []):
        kind = classify_severity_change(before, after)
        if kind:
            buckets[kind].append((path, before, after))
    return buckets


def format_severity_verdict(buckets):
    """Which direction each of the diff's severity flips went.

    The generator's diff has already listed every flipped path under SEVERITY CHANGED.
    What it cannot say is which of them widen, and that is the only thing the gate acts
    on, so this classifies rather than re-listing: a count per direction, and the
    transitions that produced it. Unrecognised severities DO get their paths, because
    they refuse and the reader has to go and look at them.
    """
    if not any(buckets.values()):
        return []
    lines = ["  severity direction (SEVERITY CHANGED above, classified):"]
    for kind, label in (("widened", "WIDENS enforcement "),
                        ("narrowed", "NARROWS enforcement")):
        rows = buckets[kind]
        if rows:
            pairs = Counter(f"{was} -> {now}" for _, was, now in rows)
            detail = ", ".join(f"{t} x{n}" if n > 1 else t for t, n in pairs.most_common())
            lines.append(f"    {label}: {len(rows)}  ({detail})")
    if buckets["unknown"]:
        lines.append(f"    UNRECOGNISED     : {len(buckets['unknown'])} — no rank for these:")
        lines += [f"      {p}: {was} -> {now}" for p, was, now in buckets["unknown"]]
    return lines


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

class Acknowledgements:
    """The four counts an operator can supply, and whether any were.

    Counts rather than booleans, for the reason the generator's gate uses counts: a
    `--accept-added 12` pasted out of a runbook stops agreeing the moment the install
    would add a thirteenth path, which is precisely when someone needs to look again.
    A boolean would keep passing forever.
    """

    def __init__(self, added=None, removed=None, widened=None, narrowed=None):
        self.added = added
        self.removed = removed
        self.widened = widened
        self.narrowed = narrowed


def gate_install(diff, ack, enforced_changes, out=None):
    """True to proceed with the copy, False to refuse.

    Four independent counts, each refusing on its own. They are separate flags rather
    than one total because they are different decisions: a path entering enforcement,
    a path leaving it, a file starting to score, and a file stopping. Collapsing them
    into one number would let an addition and a removal cancel out to zero.

    `unknown` severity transitions take no accept flag at all. There is nothing to
    acknowledge a count of when the script cannot say which direction the change went;
    the fix is to teach SEVERITY_RANK the new value, in a commit someone reviews.

    `out` is resolved per call, never bound as a default, so a caller that redirected
    stderr still sees the refusals.
    """
    out = sys.stderr if out is None else out
    sev = severity_transitions(diff)
    ok = True

    checks = (
        ("--accept-added", len(enforced_changes(diff["added"])), ack.added,
         "enforced path(s) entering scope"),
        ("--accept-removed", len(enforced_changes(diff["removed"])), ack.removed,
         "enforced path(s) leaving scope"),
        ("--accept-widened", len(sev["widened"]), ack.widened,
         "path(s) whose severity now scores against a player"),
        ("--accept-narrowed", len(sev["narrowed"]), ack.narrowed,
         "path(s) whose severity no longer scores"),
    )

    for flag, observed, accepted, noun in checks:
        if observed == 0 and accepted is None:
            continue
        if accepted is None:
            print(f"  REFUSED: {observed} {noun}. Read the diff above, then re-run with "
                  f"{flag} {observed}.", file=out)
            ok = False
        elif accepted != observed:
            # Including when `observed` is now ZERO. A count supplied for a change that
            # has since disappeared is the same staleness as a count that is too low, and
            # ignoring it would let a run be waved through on an acknowledgement of
            # something that is no longer in the diff.
            print(f"  REFUSED: {flag} {accepted} does not match the {observed} {noun}. "
                  "The manifest changed since you looked.", file=out)
            ok = False
        else:
            print(f"  accepted: {observed} {noun} ({flag} {accepted})", file=out)

    if sev["unknown"]:
        print(f"  REFUSED: {len(sev['unknown'])} severity transition(s) this script cannot "
              "rank. No --accept flag covers them: add the severity to SEVERITY_RANK in "
              "scripts/install-game-files-manifest.py first.", file=out)
        ok = False

    if ok and not any(observed for _, observed, _, _ in checks):
        print("  gate: nothing enforced entered or left scope, and no severity moved.",
              file=out)
    return ok


# --------------------------------------------------------------------------
# Remote side
# --------------------------------------------------------------------------

def resolve_installed_path(ssh, appsettings_path=DEFAULT_APPSETTINGS,
                           fallback=DEFAULT_MANIFEST_PATH, out=None):
    """The manifest path the API actually reads.

    `GameFilesManifestPath` in appsettings.json overrides the compiled-in default, so
    a run that assumed the default would happily back up and replace a file the API
    never opens — an install that changed nothing, reporting success. Every failure to
    read the config is announced and falls back rather than aborting: appsettings.json
    is mode 600 and holds secrets, and an unreadable one is a permissions story, not a
    reason to refuse to install.
    """
    out = sys.stderr if out is None else out
    program = ("import json;"
               f"print(json.load(open({appsettings_path!r})).get('GameFilesManifestPath') or '')")
    _, stdout, stderr = ssh.exec_command("python3 -c " + shlex.quote(program))
    value = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    if value:
        if value != fallback:
            print(f"  installed path: {value} (from GameFilesManifestPath, NOT the "
                  f"default {fallback})", file=out)
        return value
    reason = err.splitlines()[-1] if err else "key absent"
    print(f"  installed path: {fallback} (config gave nothing: {reason})", file=out)
    return fallback


def read_remote_manifest(sftp, path):
    """(manifest, raw_bytes, reason). `manifest` is None unless it parsed as one.

    🔑 `raw_bytes` is returned whenever the READ succeeded, even when the parse did not,
    and the two answer different questions. "Is there a baseline to gate against?" is
    about the parse. "Is there a file here that must be backed up before I replace it?"
    is about the read — and conflating them means an installed manifest that has become
    unparseable (truncated by a half-finished hand copy, say) is treated as absent and
    overwritten with no backup, which is precisely the file you would most want back.

    The bytes also spare the byte-identical check a second read of a 190KB file.
    """
    try:
        with sftp.open(path, "rb") as f:
            raw = f.read()
    except OSError as exc:
        return None, None, f"{path} could not be read ({exc})"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return None, raw, f"{path} is not valid JSON ({exc})"
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return None, raw, f"{path} has no files[] — not a manifest"
    return data, raw, None


SAFE_REASON = re.compile(r"[^A-Za-z0-9._-]+")


def backup_name(installed_path, reason, when=None, taken=()):
    """`<installed>.bak-<reason>-<YYYYMMDD>`, matching what is already on the box.

    The reason is squeezed to a safe token because it lands in a shell-free SFTP path
    but still has to be readable in an `ls`, and because a stray quote or slash in an
    operator's `--reason` would otherwise write the backup somewhere other than beside
    the manifest.

    A day-granular name collides on the second install of a day under the same reason,
    and the collision would overwrite the only copy of what was live this morning with
    a copy of what has been live since lunchtime — the rollback target quietly becoming
    the thing you are rolling back from. A taken name gains the time, which is a shape
    already on the box.
    """
    when = when or datetime.now(timezone.utc)
    token = SAFE_REASON.sub("-", reason).strip("-").lower() or "install"
    name = f"{installed_path}.bak-{token}-{when.strftime('%Y%m%d')}"
    if name in taken:
        name = f"{name}-{when.strftime('%H%M%S')}"
    return name


def existing_backup_names(sftp, installed_path):
    """Backup names already beside the manifest, for collision avoidance only.

    `listdir` on the containing directory reads names; it opens, moves and deletes
    nothing. It is also the one place this needs to know what else is in there, and
    `uploads/` and `releases/` are exactly the entries it must keep its hands off —
    so the result is filtered to names derived from the manifest before it is used.
    """
    directory, _, base = installed_path.rpartition("/")
    try:
        names = sftp.listdir(directory or ".")
    except OSError:
        return set()
    prefix = base + ".bak-"
    return {f"{directory}/{n}" for n in names if n.startswith(prefix)}


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def install(sftp, installed_path, payload, reason, had_previous, out=None):
    """Back up, write atomically, verify. Returns the backup path, or None on a first install.

    The staged temp file sits in the manifest's own directory rather than /tmp because
    the rename that publishes it is only atomic within one filesystem. The API caches
    the parsed manifest keyed on the file's mtime alone, so a partially written file
    would be read and served as gospel; a rename means the path never holds anything
    but a complete document.

    Named files throughout. Nothing here globs, lists or removes a directory: the
    manifest's neighbours are `uploads/` (the evidence corpus) and `releases/`.
    """
    out = sys.stderr if out is None else out
    backup = None
    if had_previous:
        backup = backup_name(installed_path, reason,
                             taken=existing_backup_names(sftp, installed_path))
        with sftp.open(installed_path, "rb") as src, sftp.open(backup, "wb") as dst:
            dst.write(src.read())
        sftp.chmod(backup, 0o644)
        print(f"  backup:    {backup}", file=out)
    else:
        print("  backup:    none taken — nothing was installed there", file=out)

    # posix_rename, not rename: plain SFTP rename is specified to FAIL when the target
    # exists, and the target always exists here. A server without the OpenSSH extension
    # raises, which is the right outcome — the alternative is an unlink-then-write with a
    # window where the API 404s.
    staged = f"{installed_path}.installing"
    try:
        with sftp.open(staged, "wb") as f:
            f.write(payload)
        sftp.chmod(staged, 0o644)
        sftp.posix_rename(staged, installed_path)
    except Exception:
        try:
            sftp.remove(staged)
        except IOError:
            pass
        raise

    with sftp.open(installed_path, "rb") as f:
        landed = f.read()
    if sha256_bytes(landed) != sha256_bytes(payload):
        raise RuntimeError(
            f"{installed_path} does not match what was sent. The file on the box is NOT the "
            f"manifest you built; restore {backup} before anything else.")
    return backup


# --------------------------------------------------------------------------

def load_local_manifest(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError(f"{path} has no files[] — not a manifest")
    return data, raw


def build_arg_parser():
    ap = argparse.ArgumentParser(
        description="Install a built game-files manifest onto the AC API host, gated.")
    ap.add_argument("--manifest", required=True,
                    help="Local manifest to install (the generator's --out)")
    ap.add_argument("--server", default=os.environ.get("KTP_AC_API_HOST"),
                    help="AC API host (default: $KTP_AC_API_HOST)")
    ap.add_argument("--user", default="root")
    ap.add_argument("--ssh-key", default=None,
                    help="Private key (default: $KTP_AC_API_SSH_KEY, else ~/.ssh/id_ed25519)")
    ap.add_argument("--reason", required=True,
                    help="Why this is being installed. Names the backup, so make it findable "
                         "in an ls six months from now (e.g. pre-weapon-kit).")
    ap.add_argument("--installed-path", default=None,
                    help="Manifest path on the host (default: read GameFilesManifestPath from "
                         f"{DEFAULT_APPSETTINGS})")
    ap.add_argument("--appsettings", default=DEFAULT_APPSETTINGS,
                    help=f"API config to resolve the manifest path from (default: {DEFAULT_APPSETTINGS})")
    ap.add_argument("--diff-limit", type=int, default=None,
                    help="Paths listed per origin in the diff, 0 for all (default: the "
                         "generator's default)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the diff and the gate's verdict, then stop before any write.")
    ap.add_argument("--no-gate", action="store_true",
                    help="BREAK GLASS: install without acknowledging anything. The --accept "
                         "flags are the normal override; this is for a first install or a "
                         "deliberate re-scope, and it is announced in the output.")
    ap.add_argument("--accept-added", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N enforced paths entering scope.")
    ap.add_argument("--accept-removed", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N enforced paths leaving scope.")
    ap.add_argument("--accept-widened", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N paths whose severity now scores (review -> violation).")
    ap.add_argument("--accept-narrowed", type=int, default=None, metavar="N",
                    help="Acknowledge exactly N paths whose severity no longer scores.")
    return ap


def connect(server, user, key_path):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(server, username=user, key_filename=key_path)
    return ssh


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    # After parse_args so --help answers without a network, and before --dry-run: a plan
    # printed by a stale copy is wrong in exactly the way that is hard to notice. `also`
    # covers the generator because its diff is what this gate decides on — a current
    # installer reading a stale diff would refuse and accept the wrong things.
    require_current(__file__, also=["build-game-files-manifest.py"],
                    purpose="replace the manifest every AC client is checked against")

    gen = load_generator()
    err = sys.stderr

    if not args.server:
        sys.exit("--server is required (or set $KTP_AC_API_HOST). No host is compiled in: "
                 "this script writes to whatever it is pointed at.")
    if args.no_gate and (args.accept_added is not None or args.accept_removed is not None
                         or args.accept_widened is not None or args.accept_narrowed is not None):
        sys.exit("--no-gate with an --accept count is contradictory: the counts ARE the "
                 "acknowledgement. Drop --no-gate and let them be checked.")

    try:
        candidate, payload = load_local_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        sys.exit(f"candidate manifest unusable: {exc}")

    key_path = (args.ssh_key or os.environ.get("KTP_AC_API_SSH_KEY")
                or str(Path.home() / ".ssh" / "id_ed25519"))
    ssh = connect(args.server, args.user, key_path)
    try:
        sftp = ssh.open_sftp()
        installed_path = args.installed_path or resolve_installed_path(
            ssh, args.appsettings, DEFAULT_MANIFEST_PATH, out=err)
        previous, previous_raw, unavailable = read_remote_manifest(sftp, installed_path)

        # Byte-identical installs are the one case worth short-circuiting: they would
        # otherwise take a backup of a file against its own twin and move the mtime,
        # which is the only thing the API's cache keys on, for no change at all.
        if previous_raw == payload:
            print("\nAlready installed: byte-identical to what is on the host. "
                  "Nothing written, no backup taken.", file=err)
            return 0

        limit = (gen.DIFF_LIST_LIMIT_DEFAULT if args.diff_limit is None else args.diff_limit)
        diff = gen.diff_manifests(previous, candidate) if previous is not None else None
        for line in gen.scope_diff_lines(previous, candidate, installed_path, unavailable,
                                         limit, diff=diff):
            print(line, file=err)

        if diff is not None:
            for line in format_severity_verdict(severity_transitions(diff)):
                print(line, file=err)

        print("\n=== Install gate ===", file=err)
        if args.no_gate:
            # Loud, and above the write rather than after it: this line is the only
            # record that an install went in unexamined.
            print("  GATE DISARMED (--no-gate). Nothing about this change was "
                  "acknowledged.", file=err)
        elif diff is None:
            # The generator warns and writes anyway here. This refuses. A regeneration
            # with no baseline reaches nobody; an install with no baseline puts an
            # unreviewed manifest in front of every player, and "the gate could not
            # compare" must never read as "the gate passed".
            print(f"  REFUSED: no installed manifest to compare against "
                  f"({unavailable}). A gate with no baseline cannot pass. If this is a "
                  "genuine first install, say so with --no-gate.", file=err)
            return 2
        else:
            ack = Acknowledgements(args.accept_added, args.accept_removed,
                                   args.accept_widened, args.accept_narrowed)
            if not gate_install(diff, ack, gen.enforced_changes, out=err):
                print(f"  {installed_path} left UNCHANGED.", file=err)
                return 2

        if args.dry_run:
            print("  --dry-run: stopping before the copy.", file=err)
            return 0

        # `previous_raw`, not `previous`: a file that exists but no longer parses still
        # gets backed up before it is replaced. See read_remote_manifest.
        backup = install(sftp, installed_path, payload, args.reason,
                         had_previous=previous_raw is not None, out=err)

        meta = candidate.get("_meta", {})
        print("\n=== Installed ===", file=err)
        print(f"  path:      {installed_path}", file=err)
        print(f"  version:   {meta.get('version')}   (severity is NOT in this hash)", file=err)
        print(f"  severity:  {meta.get('by_severity')}", file=err)
        print(f"  total:     {meta.get('total_files')} files", file=err)
        print(f"  sha256:    {sha256_bytes(payload)}", file=err)
        if backup:
            print(f"  rollback:  cp {backup} {installed_path}", file=err)
        print("  No restart: the API re-reads on mtime change. Responses carry "
              "max-age=300, so allow a few minutes.", file=err)
        return 0
    finally:
        ssh.close()


if __name__ == "__main__":
    sys.exit(main())
