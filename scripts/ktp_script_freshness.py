#!/usr/bin/env python3
"""Refuse to touch the fleet from a checkout that is behind `origin/main`.

The trap this closes, in the order it happens:

  1. A local checkout falls behind. Nothing reports that; `git status` is not
     part of anyone's deploy ritual.
  2. Someone runs `python scripts/stage-wave.py ...` from it.
  3. The old copy parses its own arguments, connects to 24 hosts, stages the
     artifacts, verifies the md5s, and prints a clean 24/24.
  4. Everything the newer version would have done that the old one has never
     heard of simply does not happen -- and no flag was rejected, because the
     old copy has no such flag to reject. An unknown flag is a usage error; a
     flag that was never passed is silence.

The loss that costs something is `--pull-live`: it downloads each artifact's
LIVE counterpart before staging, and the fleet keeps no rollback copies. The
swap is `mv -f`, and these artifacts are not byte-reproducible (`.amxx` bakes a
per-minute build stamp, ReHLDS bakes `__DATE__`). The running build is the only
copy of itself that exists, and the stale stager walks past it without a word.
The wave ledger is the same shape of loss one layer up: the wave lands, the
ledger has no entry, and `ktp-wave-ledger.py reconcile` is blind to it forever.

It happened once already and was caught by hand on the 1.23.2 wave; the ledger
entry was written afterwards from memory. The standing remedy was a sentence in
a doc -- "run it out of `git show origin/main:` instead" -- which is a rule
applied from memory, and therefore a rule applied sometimes.

WHAT IT ASKS
------------
Not "is the repo current" -- one unrelated local edit would then block a deploy.
It asks, of the file that is actually executing and of the siblings that file
loads: does this differ from `origin/main`? That is `git diff` against the ref,
and git is asked to answer it rather than a hash being recomputed here: the
checkouts set `core.autocrlf=input` and carry a `.gitattributes`, so raw bytes
and the stored blob legitimately differ and a hand-rolled comparison reports
drift on files that are identical.

FAIL-CLOSED, AND WHERE THE EDGE IS
----------------------------------
Every answer that is not "identical to the ref" refuses: drift, no checkout, the
path missing from the ref, a git invocation that fails, a fetch that fails on a
copy that otherwise looks clean. "I could not tell" and "it is fine" must not
produce the same outcome, because the whole defect is a check that returned
silence.

Freshness of the ref itself is settled at run time, by fetching. The accepted
cost is a dependency on reaching the git remote while staging. That dependency
is strictly weaker than the one the operation already has -- staging opens SSH
to 24 hosts across five providers -- so a run that can stage can fetch. The
alternative, a hash recorded in the tree, is recorded in the same file that goes
stale, and a stale copy carries a stale expectation that agrees with itself.

If the fetch fails the comparison still runs against whatever `origin/main` is
already on disk, because a copy that differs from even a KNOWN-OLD ref is a
finding that needs no network to be true. Only the clean-but-unverifiable case
needs the operator (`KTP_FRESHNESS_OFFLINE`).

INERT CONTEXTS
--------------
Under pytest and under GitHub Actions the check reports and returns. In CI the
provenance is the checked-out sha, which is recorded; in a test the harness is
not a deploy, and the suite must be able to exercise a `main()` on a branch that
is by definition not `origin/main` yet -- including the branch that changes this
file. Both are named in the output, never silent.

This guards against ACCIDENT, not evasion. Anything here is trivially bypassed
by someone who wants to; the failure it exists for is forgetting that a checkout
got old, which nothing else on this estate reports.

Env:
  KTP_FRESHNESS_REF       ref to compare against (default: origin/main)
  KTP_FRESHNESS_REPO      checkout to verify against, for a copy extracted to a
                          temp path outside any tree
  KTP_FRESHNESS_OFFLINE   non-empty reason; accepts an unfetchable ref that the
                          local comparison found clean. Never skips the compare.
  KTP_FRESHNESS_BYPASS    non-empty reason; proceeds after a refusal, printing
                          the full drift report and the reason. Exists because
                          the alternative to a recorded override is an
                          unrecorded one -- copying the file somewhere the guard
                          cannot reach costs about as much and leaves no trace.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

DEFAULT_REF = "origin/main"
_FETCH_TIMEOUT = 45
_GIT_TIMEOUT = 60
# How far back through a path's history to look for the running copy. Bounded so
# a pathological history cannot turn the guard into the slow part of a deploy;
# not finding it inside the window is reported as not-found, never as found.
_HISTORY_WINDOW = 400


class FreshnessError(RuntimeError):
    """Raised when the running file is not provably the current one."""


def _git(repo, *args, timeout=_GIT_TIMEOUT, raw=False):
    """Run git, returning (rc, stdout, stderr). Never raises on a non-zero rc.

    `raw` keeps stdout exactly as git produced it. File contents must be read
    that way: stripping costs the trailing newline, which understates every
    line count taken off the ref by one and quietly mangles a file that opens
    with a blank line.
    """
    try:
        p = subprocess.run(
            ["git", "-C", repo, *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout if raw else p.stdout.strip()), p.stderr.strip()
    except FileNotFoundError:
        return 127, "", "git not found on PATH"
    except subprocess.TimeoutExpired:
        return 124, "", f"git {' '.join(args)} timed out after {timeout}s"


def _toplevel(start_dir):
    rc, out, _ = _git(start_dir, "rev-parse", "--show-toplevel")
    return out if rc == 0 and out else None


def _long_options(text):
    """Long options a file mentions. Deliberately over-broad -- it reads
    docstrings and help text too, because a name that appears only in the usage
    block still tells the reader what the newer copy knows about, which is the
    question being answered. `--help` is dropped: argparse gives it to every
    script, so its presence or absence carries nothing."""
    return set(re.findall(r"--[a-z][a-z0-9]*(?:-[a-z0-9]+)*", text)) - {"--help"}


def _top_level_names(text):
    return set(re.findall(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", text, re.M))


def _blob(repo, ref, rel):
    rc, out, _ = _git(repo, "show", f"{ref}:{rel}", raw=True)
    return out if rc == 0 else None


def _matching_commit(repo, ref, rel):
    """The most recent commit on `ref` whose version of `rel` is what is on disk.

    Returns (sha, commits_since) or (None, None). `None` means the running copy
    is not any recorded version of this path -- a hand-edit, a partial merge, or
    a file from another branch -- which is a different and worse finding than
    being behind by a known number of commits, and is reported as such.
    """
    rc, out, _ = _git(repo, "log", f"--max-count={_HISTORY_WINDOW}",
                      "--format=%H", ref, "--", rel)
    if rc != 0 or not out:
        return None, None
    for depth, sha in enumerate(out.splitlines()):
        if _git(repo, "diff", "--quiet", sha, "--", rel)[0] == 0:
            return sha, depth
    return None, None


def _describe_drift(repo, ref, rel):
    """What the reader would have lost. Every number here is computed."""
    lines = []
    disk_path = os.path.join(repo, rel)
    try:
        with open(disk_path, "r", encoding="utf-8", errors="replace") as fh:
            running = fh.read()
    except OSError as exc:
        running = ""
        lines.append(f"    (could not read {disk_path}: {exc})")
    current = _blob(repo, ref, rel) or ""

    missing_opts = sorted(_long_options(current) - _long_options(running))
    if missing_opts:
        lines.append("    flags on %s that this copy does not have:" % ref)
        lines.append("      " + "  ".join(missing_opts))

    missing_names = sorted(_top_level_names(current) - _top_level_names(running))
    if missing_names:
        lines.append("    functions/classes on %s that this copy does not have:" % ref)
        lines.append("      " + "  ".join(missing_names))

    gained_opts = sorted(_long_options(running) - _long_options(current))
    if gained_opts:
        lines.append("    present here and NOT on %s (local or unmerged work):" % ref)
        lines.append("      " + "  ".join(gained_opts))

    running_lines = running.count("\n")
    current_lines = current.count("\n")
    lines.append(f"    size: {running_lines} lines here, {current_lines} on {ref}")

    sha, since = _matching_commit(repo, ref, rel)
    if sha is None:
        lines.append(f"    this copy matches NO commit of {rel} in the last "
                     f"{_HISTORY_WINDOW} touching {ref} -- it is not merely old, "
                     f"it is a version that was never on the ref")
    else:
        lines.append(f"    this copy is {sha[:12]}, {since} commit(s) behind "
                     f"{ref} on this path:")
        rc, out, _ = _git(repo, "log", "--format=      %h %s", f"{sha}..{ref}", "--", rel)
        if rc == 0 and out:
            lines.extend(out.splitlines())

    rc, out, _ = _git(repo, "rev-list", "--count", f"HEAD..{ref}")
    if rc == 0 and out:
        lines.append(f"    (whole checkout is {out} commit(s) behind {ref})")

    return lines


def _inert_context():
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return "pytest"
    if os.environ.get("GITHUB_ACTIONS"):
        return "github-actions"
    return None


def check(script_path, also=()):
    """Compare the running file (and `also`, its sibling loads) against the ref.

    Returns a list of human-readable problem blocks; empty means verified
    current. Raising is left to require_current() so a caller can ask without
    being exited.
    """
    ref = os.environ.get("KTP_FRESHNESS_REF") or DEFAULT_REF
    script_path = os.path.abspath(script_path)
    here = os.path.dirname(script_path)

    repo = os.environ.get("KTP_FRESHNESS_REPO") or _toplevel(here)
    if not repo:
        return [
            f"Cannot verify {os.path.basename(script_path)} is current: it is not "
            f"inside a git checkout.\n"
            f"  looked from: {here}\n"
            f"  A copy extracted to a temp path has no provenance and this guard "
            f"will not assume one.\n"
            f"  Run it from the checkout, or point KTP_FRESHNESS_REPO at the "
            f"checkout whose {ref} it should be compared against."
        ]
    repo = os.path.abspath(repo)

    targets = []
    for path in (script_path, *(os.path.join(here, name) for name in also)):
        path = os.path.abspath(path)
        try:
            rel = os.path.relpath(path, repo).replace(os.sep, "/")
        except ValueError:
            return [f"Cannot verify {path}: it is not under {repo}."]
        if rel.startswith(".."):
            return [f"Cannot verify {path}: it is not under {repo}."]
        targets.append(rel)

    remote, _, branch = ref.partition("/")
    fetch_rc, _, fetch_err = _git(repo, "fetch", "--quiet", remote, branch,
                                  timeout=_FETCH_TIMEOUT)

    problems = []
    for rel in targets:
        if _git(repo, "cat-file", "-e", f"{ref}:{rel}")[0] != 0:
            problems.append(
                f"Cannot verify {rel}: it does not exist at {ref}.\n"
                f"  Either {ref} is not fetched in this checkout, or this file is "
                f"not on the ref. Both mean its provenance is unknown, and a file "
                f"of unknown provenance does not get to write to the fleet."
            )
            continue

        rc, _, err = _git(repo, "diff", "--quiet", ref, "--", rel)
        if rc == 0:
            continue
        if rc != 1:
            problems.append(
                f"Cannot verify {rel}: `git diff` exited {rc}.\n"
                f"  {err or '(no stderr)'}\n"
                f"  Undetermined is not clean."
            )
            continue

        block = [f"{rel} DIFFERS from {ref}."]
        block.extend(_describe_drift(repo, ref, rel))
        block.append(f"    see the whole difference: "
                     f"git -C {repo} diff {ref} -- {rel}")
        problems.append("\n".join(block))

    if problems:
        # Drift against a ref that could not be refreshed is still drift. Say so
        # rather than muddying a real finding with a network caveat.
        return problems

    if fetch_rc != 0:
        offline = os.environ.get("KTP_FRESHNESS_OFFLINE", "").strip()
        detail = (f"Could not fetch {remote} {branch}: "
                  f"{fetch_err or f'git fetch exited {fetch_rc}'}")
        if not offline:
            return [
                f"{detail}\n"
                f"  The files match the {ref} already on disk, but nothing here "
                f"proves that ref is current, and a ref that has not moved since "
                f"the checkout went stale agrees with a stale copy.\n"
                f"  Fix the network, or set KTP_FRESHNESS_OFFLINE to a reason to "
                f"accept the on-disk ref."
            ]
        print(f"[freshness] ACCEPTING AN UNVERIFIED {ref}: {offline}", file=sys.stderr)
        print(f"[freshness]   {detail}", file=sys.stderr)

    return []


def require_current(script_path, also=(), purpose=None):
    """Gate a fleet-writing entry point. Call it first thing in main().

    Place it AFTER parse_args so `--help` still answers without a network, and
    BEFORE any work -- including a dry run, because a dry run from a stale copy
    prints a plan that is wrong in exactly the way that is hard to notice.
    """
    name = os.path.basename(script_path)
    inert = _inert_context()
    if inert:
        print(f"[freshness] not gating ({inert}); provenance is the checked-out tree",
              file=sys.stderr)
        return

    problems = check(script_path, also=also)
    if not problems:
        return

    what = purpose or "write to the fleet"
    banner = [
        "",
        "=" * 78,
        f"REFUSING TO RUN {name}: it is not provably the current version.",
        "=" * 78,
    ]
    for block in problems:
        banner.append("")
        banner.append("  " + block.replace("\n", "\n  "))
    banner += [
        "",
        f"  This script can {what}. A version that is behind does not reject the",
        "  flags it lacks -- it never sees them, stages anyway, and reports success.",
        "",
        "  Refresh the checkout, then run it again.",
        "=" * 78,
        "",
    ]
    text = "\n".join(banner)

    bypass = os.environ.get("KTP_FRESHNESS_BYPASS", "").strip()
    if bypass:
        print(text, file=sys.stderr)
        print(f"[freshness] BYPASSED ON PURPOSE: {bypass}", file=sys.stderr)
        print("[freshness] Everything above is still true.", file=sys.stderr)
        return

    print(text, file=sys.stderr)
    raise SystemExit(3)


if __name__ == "__main__":
    # Reporting mode: name the drift for a path without running anything.
    import argparse

    ap = argparse.ArgumentParser(description="Report whether a script is current.")
    ap.add_argument("path", nargs="+", help="Script(s) to check.")
    args = ap.parse_args()
    bad = 0
    for p in args.path:
        found = check(p)
        if found:
            bad = 1
            for block in found:
                print(block, file=sys.stderr)
        else:
            print(f"{p}: current")
    raise SystemExit(bad)
