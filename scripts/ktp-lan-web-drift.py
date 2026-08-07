#!/usr/bin/env python3
"""ktp-lan-web-drift — does /opt/lan-web match sites/lan-web in the repo?

/opt/lan-web was hand-copied from June onward: no deploy script, no drift
check, 19 .deploy-bak-* directories as the fossil record. The cost was
concrete. On 2026-08-07 a file-level compare found the box running the PRE-fix
bracket.py -- the placement fix had been pushed to main on 08-02 and never
deployed -- while a 22-line warmup panel existed ONLY on the box and would
have been deleted by the first rsync from source.

Reports only; deploying is deploy-lan-web.sh's job. Three states matter and
they are NOT the same problem, so they are counted separately:

  differ    -- both sides have it, contents disagree (which side is right is
               a human call; that is why this does not auto-deploy)
  box-only  -- exists only on the server. A deploy with --delete DESTROYS it.
  repo-only -- committed but never deployed.

Line endings are normalised before comparing. The box was copied from Windows
so its files carry CRLF; without normalising, every file reads as drifted and
the real signal is buried under 57 false positives.

Exit codes: 0 = in sync, 1 = drift (detail on stdout), 2 = check failed
(SSH/path error -- log it, do not alert; a transient failure must not flap).
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import sys

try:
    import paramiko
except ImportError:
    print("paramiko not available", file=sys.stderr)
    sys.exit(2)

REMOTE_ROOT = "/opt/lan-web/app"
SUFFIXES = (".py", ".html", ".css", ".js", ".txt", ".ini", ".json")
SKIP_DIRS = {"__pycache__", "venv", ".venv", "node_modules", ".git"}


def _norm(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def local_manifest(root: str) -> dict[str, str]:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(SUFFIXES):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, "rb") as fh:
                out[rel] = _norm(fh.read())
    return out


def remote_manifest(sftp, root: str) -> dict[str, str]:
    out = {}
    stack = [root]
    while stack:
        cur = stack.pop()
        for entry in sftp.listdir_attr(cur):
            name = entry.filename
            full = posixpath.join(cur, name)
            if entry.st_mode is not None and (entry.st_mode & 0o40000):
                if name not in SKIP_DIRS:
                    stack.append(full)
                continue
            if not name.endswith(SUFFIXES):
                continue
            with sftp.open(full, "rb") as fh:
                out[posixpath.relpath(full, root)] = _norm(fh.read())
    return out


def main() -> int:
    repo_root = os.environ.get(
        "LAN_WEB_SRC",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "sites", "lan-web", "app"))
    if not os.path.isdir(repo_root):
        print("source tree not found: %s" % repo_root, file=sys.stderr)
        return 2

    host = os.environ.get("DATA_SSH_HOST", "74.91.112.242")
    user = os.environ.get("DATA_SSH_USER", "root")
    key = os.environ.get("DATA_SSH_KEY", os.path.expanduser("~/.ssh/id_ed25519"))

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=user, key_filename=key, timeout=30,
                       allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()
        box = remote_manifest(sftp, REMOTE_ROOT)
        sftp.close()
    except Exception as exc:                                  # noqa: BLE001
        print("check failed: %s" % exc, file=sys.stderr)
        return 2
    finally:
        client.close()

    repo = local_manifest(repo_root)
    if not repo or not box:
        # an empty manifest compares "clean" against anything; refuse to say OK
        print("empty manifest (repo=%d box=%d) -- check the paths, not the result"
              % (len(repo), len(box)), file=sys.stderr)
        return 2

    differ = sorted(f for f in set(repo) & set(box) if repo[f] != box[f])
    box_only = sorted(set(box) - set(repo))
    repo_only = sorted(set(repo) - set(box))

    print("lan-web: %d files repo / %d box" % (len(repo), len(box)))
    if not (differ or box_only or repo_only):
        print("in sync")
        return 0

    if box_only:
        print("\nBOX-ONLY (%d) -- a deploy with --delete would DESTROY these:" % len(box_only))
        for f in box_only:
            print("   + %s" % f)
    if repo_only:
        print("\nREPO-ONLY (%d) -- committed, never deployed:" % len(repo_only))
        for f in repo_only:
            print("   - %s" % f)
    if differ:
        print("\nDIFFER (%d) -- contents disagree:" % len(differ))
        for f in differ:
            print("   ! %s" % f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
