#!/usr/bin/env python3
"""Stage a KTP_TEST_MODE plugin build to the Tier-2 runner, and record what was staged.

This owns the one seam in the Tier-2 pipeline that had no tool behind it. The
runner's test-mode plugins were restaged by hand (`scp`), and the "which build
is the runner holding?" answer lived in a hardcoded literal inside the test
(`EXPECTED_KTPMATCHHANDLER_VERSION = ... or "0.10.147"`) that a human had to
remember to bump. It rotted on 2026-08-03: the runner sat two versions behind
the artifact about to be waved and every behaviour test still passed, because
the only thing that could have caught it was that literal.

  1. MD5 PIN. `--expect <md5>` refuses to stage a build whose local md5 doesn't
     match what you reviewed. KTPMatchHandler bakes a per-minute BUILD_TIME, so
     an accidental rebuild silently changes the artifact. Same guarantee, and
     the same reasoning, as stage-wave.py's --expect.

  2. POST-TRANSFER VERIFY. md5 is re-read from the runner after the upload. A
     transfer that "succeeded" but landed truncated is a green suite certifying
     a binary nobody built.

  3. MANIFEST. Writes {plugin: {version, md5, staged_at, staged_by}} to the
     runner, so the suite can assert loaded == manifest instead of loaded ==
     literal. Self-maintaining: staging IS the update. The version cannot be
     read back out of a compiled .amxx (XXMA+zlib -- `strings` returns nothing
     even for text that is certainly present), which is exactly why the stager
     has to record it rather than the test discovering it.

It does NOT restart anything -- the Tier-2 workflow starts its own hlds per run.

Ordering, which matters: restage the runner only AFTER a wave has activated and
post-activation verify passes, because the runner mirrors the LIVE fleet. The
one deliberate exception is the pre-activation gate, where the runner is meant
to lead the fleet so a reviewed build can be smoke-tested before it waves -- in
that case pass the version to the workflow (`matchhandler_version`) as well, so
the env override wins over the manifest for that run.

Usage:
  # restage MatchHandler's test build and record it
  stage-runner.py -f compiled/KTPMatchHandler_testmode.amxx --as KTPMatchHandler.amxx \
                  --version 0.10.150 --expect 4b3e524579e2b481245fccdaf94565f7

  # what does the runner hold right now?
  stage-runner.py --show

  # inspect intent without connecting
  stage-runner.py -f x.amxx --as KTPMatchHandler.amxx --version 0.10.150 --dry-run

Env: KTP_TIER2_SSH_HOST (required)  KTP_TIER2_SSH_USER (default root)
     KTP_TIER2_SSH_PASSWORD         KTP_TIER2_TREE (default /opt/ktp-tier2-runner/serverfiles)
     KTP_TIER2_MANIFEST (default <tree>/../stage-manifest.json)
No default host: this tool holds no IPs, and staging to a guessed host is worse
than failing.
"""

import argparse
import getpass
import hashlib
import json
import os
import posixpath
import sys
import time

try:
    import paramiko
except ImportError:
    print("ERROR: paramiko not installed. Run: pip install paramiko")
    sys.exit(1)

HOST = os.environ.get("KTP_TIER2_SSH_HOST", "")
USER = os.environ.get("KTP_TIER2_SSH_USER", "root")
TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
PLUGIN_DIR = "dod/addons/ktpamx/plugins"
MANIFEST = os.environ.get(
    "KTP_TIER2_MANIFEST", posixpath.join(posixpath.dirname(TREE), "stage-manifest.json")
)

# Plugins the runner runs as KTP_TEST_MODE builds. Mirrors PLUGINS_TESTMODE in
# ktp-tier2-stack-drift.py and RUNNER_TESTMODE_PLUGINS in stage-wave.py --
# three lists, one fact. Keep them in step.
TESTMODE_PLUGINS = {"KTPMatchHandler.amxx", "KTPPracticeMode.amxx", "KTPHudObserver.amxx"}


def local_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def connect():
    if not HOST:
        sys.exit("FATAL: KTP_TIER2_SSH_HOST is unset. Set it -- this tool ships no default host.")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, username=USER, password=os.environ.get("KTP_TIER2_SSH_PASSWORD") or None,
                timeout=30)
    return ssh


def run(ssh, cmd, timeout=60):
    _, so, se = ssh.exec_command(cmd, timeout=timeout)
    return so.read().decode(errors="replace").strip(), se.read().decode(errors="replace").strip()


def read_manifest(ssh):
    out, _ = run(ssh, f"cat '{MANIFEST}' 2>/dev/null")
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # Don't silently reset a manifest we failed to parse -- that would erase
        # the record of every other plugin to fix one.
        sys.exit(f"FATAL: {MANIFEST} on the runner is not valid JSON. Inspect it by hand.")


def show(ssh):
    man = read_manifest(ssh)
    names = sorted(TESTMODE_PLUGINS | set(man))
    print(f"Runner {USER}@{HOST}")
    print(f"  tree     {TREE}")
    print(f"  manifest {MANIFEST}{'' if man else '  (absent or empty)'}\n")
    paths = " ".join(f"'{TREE}/{PLUGIN_DIR}/{n}'" for n in names)
    out, _ = run(ssh, f"md5sum {paths} 2>/dev/null")
    on_disk = {}
    for ln in out.splitlines():
        p = ln.split()
        if len(p) == 2:
            on_disk[posixpath.basename(p[1])] = p[0].lower()
    print(f"{'plugin':<26} {'version':<12} {'manifest md5':<34} on-disk")
    for n in names:
        e = man.get(n, {})
        disk = on_disk.get(n, "ABSENT")
        mmd5 = e.get("md5", "-")
        flag = ""
        if disk != "ABSENT" and mmd5 != "-" and disk != mmd5:
            flag = "  <-- MANIFEST DISAGREES WITH DISK"
        elif disk == "ABSENT":
            flag = "  <-- not on the runner"
        print(f"{n:<26} {e.get('version','-'):<12} {mmd5:<34} {disk}{flag}")
    return man


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-f", "--file", help="Local test-mode .amxx to stage.")
    ap.add_argument("--as", dest="as_name",
                    help="Basename on the runner (test builds are often named differently locally).")
    ap.add_argument("--version", help="Version this build reports, e.g. 0.10.150. Recorded in the manifest.")
    ap.add_argument("--expect", metavar="MD5", help="Pin the local md5 to the reviewed build.")
    ap.add_argument("--show", action="store_true", help="Print what the runner holds and exit.")
    ap.add_argument("--dry-run", action="store_true", help="Print intent, do not connect.")
    ap.add_argument("--allow-untracked", action="store_true",
                    help="Stage a plugin that is not a known test-mode plugin.")
    args = ap.parse_args()

    if args.show:
        ssh = connect()
        try:
            show(ssh)
        finally:
            ssh.close()
        return

    if not (args.file and args.as_name and args.version):
        sys.exit("FATAL: -f, --as and --version are all required (or use --show).\n"
                 "       --version cannot be derived: the version is not readable from a compiled .amxx.")
    if not os.path.isfile(args.file):
        sys.exit(f"FATAL: local file not found: {args.file}")
    if args.as_name not in TESTMODE_PLUGINS and not args.allow_untracked:
        sys.exit(f"FATAL: '{args.as_name}' is not a known test-mode plugin "
                 f"({', '.join(sorted(TESTMODE_PLUGINS))}). Use --allow-untracked if that is deliberate.")

    md5 = local_md5(args.file)
    if args.expect and md5 != args.expect.strip().lower():
        sys.exit(f"FATAL: local md5 does not match --expect (accidental rebuild?):\n"
                 f"  got      {md5}\n  expected {args.expect.strip().lower()}\n"
                 "Aborting (nothing staged). A rebuild churns md5 -- ship the reviewed artifact.")
    if not args.expect:
        print(f"WARNING: not md5-pinned (no --expect): {args.as_name}")

    remote = f"{TREE}/{PLUGIN_DIR}/{args.as_name}"
    print(f"Stage {args.file}\n   -> {USER}@{HOST or '<unset>'}:{remote}")
    print(f"   version {args.version}  md5 {md5}\n")

    if args.dry_run:
        print("DRY-RUN: no connection made. Above is what would stage.")
        return

    ssh = connect()
    try:
        man = read_manifest(ssh)
        prev = man.get(args.as_name, {})

        # Back up whatever is there, matching the existing on-runner convention.
        stamp = time.strftime("%Y%m%d-%H%M%S")
        out, _ = run(ssh, f"test -f '{remote}' && cp -p '{remote}' '{remote}.bak-{stamp}' && echo BACKED")
        print(f"  backup: {'{}.bak-{}'.format(args.as_name, stamp) if out == 'BACKED' else 'none (no existing file)'}")

        sftp = ssh.open_sftp()
        try:
            sftp.put(args.file, remote)
        finally:
            sftp.close()

        got, _ = run(ssh, f"md5sum '{remote}' 2>/dev/null | cut -d' ' -f1")
        if got.lower() != md5:
            sys.exit(f"FATAL: post-transfer md5 mismatch: runner has {got or 'NOTHING'}, expected {md5}.\n"
                     f"The previous build is at {remote}.bak-{stamp} -- restore it before running the suite.")
        print(f"  uploaded + verified: {got}")

        man[args.as_name] = {
            "version": args.version,
            "md5": md5,
            "staged_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "staged_by": f"{getpass.getuser()} via stage-runner.py",
            "previous": {k: prev.get(k) for k in ("version", "md5")} if prev else None,
        }
        payload = json.dumps(man, indent=2, sort_keys=True)
        # Write via a temp file + mv so a suite reading the manifest mid-write
        # never sees a half-written file.
        tmp = f"{MANIFEST}.tmp.{stamp}"
        sftp = ssh.open_sftp()
        try:
            with sftp.file(tmp, "w") as fh:
                fh.write(payload)
            run(ssh, f"mv -f '{tmp}' '{MANIFEST}'")
        finally:
            sftp.close()
        print(f"  manifest updated: {MANIFEST}")
    finally:
        ssh.close()

    print("\n" + "=" * 70)
    print(f"RUNNER STAGED: {args.as_name} {args.version} ({md5})")
    if prev.get("version"):
        print(f"  was: {prev['version']} ({prev.get('md5','?')})")
    print("\nThe suite now reads this version from the manifest -- no literal to bump.")
    print("For a PRE-ACTIVATION gate run, also pass the version to the workflow so the")
    print("env override wins for that run:")
    print(f"  gh workflow run tier2-integration.yml -f matchhandler_version={args.version}")
    print("\nAnd when you wave the matching PRODUCTION build, gate it on this runner:")
    print(f"  stage-wave.py -f <production .amxx> --expect-runner {args.as_name}={md5}")
    print("=" * 70)


if __name__ == "__main__":
    main()
