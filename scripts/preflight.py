"""Deploy pre-flight: assert CI on HEAD is green before pushing artifacts.

Catches the regression class where a developer compiles + deploys without
realising their last commit broke smoke. Same idea as `git push --force`
guards: a small wall against acting on stale signal.

Usage as a library (preferred for deploy scripts):

    from preflight import assert_ci_passing, PreflightError
    try:
        assert_ci_passing()
    except PreflightError as e:
        print(f"REFUSING TO DEPLOY: {e}")
        sys.exit(1)

Usage as a CLI:

    python -m preflight check                      # current repo, current HEAD
    python -m preflight check --repo-root /path
    python -m preflight check --force              # skip the gate (logged)
    python -m preflight check --workflow smoke.yml # check one workflow only

Requires the `gh` CLI to be installed and authenticated. On a dev machine,
`gh auth login` covers this; in CI, GITHUB_TOKEN is sufficient.

Exits 0 on green, 1 on PreflightError, 2 on infrastructure error
(missing `gh`, not a git repo, etc).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


class PreflightError(Exception):
    """Raised when CI is not green for the current HEAD."""


@dataclass(frozen=True)
class WorkflowRun:
    name: str
    status: str         # queued, in_progress, completed
    conclusion: str     # success, failure, cancelled, skipped, '' if running
    url: str
    head_sha: str

    @property
    def is_complete_and_green(self) -> bool:
        return self.status == "completed" and self.conclusion == "success"


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing output. Raises on non-zero exit; the caller
    decides whether to surface as PreflightError or infra error."""
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=True,
        text=True,
        capture_output=True,
    )


def get_head_sha(repo_root: Path) -> str:
    try:
        result = _run(["git", "rev-parse", "HEAD"], cwd=repo_root)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise PreflightError(f"not a git repo or git missing: {repo_root}") from exc
    return result.stdout.strip()


def get_branch(repo_root: Path) -> str:
    try:
        result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    except subprocess.CalledProcessError as exc:
        raise PreflightError("could not determine branch (detached HEAD?)") from exc
    return result.stdout.strip()


def list_runs_for_commit(
    repo_root: Path,
    sha: str,
    workflow: str | None = None,
) -> list[WorkflowRun]:
    """Query `gh run list` for runs touching `sha`. Optionally filter to one
    workflow file (e.g. `smoke.yml`)."""
    cmd = [
        "gh", "run", "list",
        "--commit", sha,
        "--limit", "50",
        "--json", "name,status,conclusion,url,headSha",
    ]
    if workflow:
        cmd += ["--workflow", workflow]

    try:
        result = _run(cmd, cwd=repo_root)
    except FileNotFoundError as exc:
        raise PreflightError(
            "gh CLI not installed. Install from https://cli.github.com/ "
            "or use --force to bypass the gate."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PreflightError(
            f"gh run list failed: {exc.stderr.strip()}\n"
            "Run `gh auth login` to authenticate, or --force to bypass."
        ) from exc

    runs_json = json.loads(result.stdout or "[]")
    return [
        WorkflowRun(
            name=r["name"],
            status=r["status"],
            conclusion=r.get("conclusion") or "",
            url=r["url"],
            head_sha=r["headSha"],
        )
        for r in runs_json
    ]


def assert_ci_passing(
    repo_root: Path | str = ".",
    *,
    workflow: str | None = None,
    force: bool = False,
) -> list[WorkflowRun]:
    """Block deploy unless CI on HEAD is green.

    Returns the list of relevant runs on success. Raises PreflightError if:
    - HEAD has no associated workflow runs (CI hasn't started or didn't fire)
    - Any run is in_progress or queued (not finished yet)
    - Any run has conclusion != success

    If `force=True`, the failure paths log a warning but return [] instead
    of raising — for emergency hotfix scenarios. Use sparingly.
    """
    repo_root = Path(repo_root).resolve()
    sha = get_head_sha(repo_root)

    runs = list_runs_for_commit(repo_root, sha, workflow=workflow)

    if not runs:
        msg = (
            f"No CI workflow runs found for HEAD {sha[:8]}. "
            "Push the commit and wait for CI to run, or --force to bypass."
        )
        if force:
            print(f"WARNING: {msg}", file=sys.stderr)
            return []
        raise PreflightError(msg)

    in_flight = [r for r in runs if r.status != "completed"]
    if in_flight:
        names = ", ".join(f"{r.name}({r.status})" for r in in_flight)
        msg = f"CI runs still in flight on {sha[:8]}: {names}. Wait for them to finish."
        if force:
            print(f"WARNING: {msg}", file=sys.stderr)
            return runs
        raise PreflightError(msg)

    failed = [r for r in runs if not r.is_complete_and_green]
    if failed:
        names = "\n  ".join(f"{r.name} ({r.conclusion}) {r.url}" for r in failed)
        msg = f"CI failure(s) on {sha[:8]}:\n  {names}"
        if force:
            print(f"WARNING: {msg}", file=sys.stderr)
            return runs
        raise PreflightError(msg)

    print(
        f"preflight: OK — {len(runs)} workflow run(s) green on {sha[:8]}",
        file=sys.stderr,
    )
    return runs


# --- CLI

def _cmd_check(args: argparse.Namespace) -> int:
    try:
        assert_ci_passing(
            repo_root=args.repo_root,
            workflow=args.workflow,
            force=args.force,
        )
        return 0
    except PreflightError as exc:
        print(f"REFUSING TO PROCEED: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="preflight")
    sub = p.add_subparsers(dest="cmd", required=True)

    chk = sub.add_parser("check", help="Assert CI is green for HEAD")
    chk.add_argument("--repo-root", default=".", help="Path to the git repo (default: cwd)")
    chk.add_argument(
        "--workflow",
        default=None,
        help="Filter to one workflow file (e.g. smoke.yml). Default: all workflows.",
    )
    chk.add_argument(
        "--force",
        action="store_true",
        help="Bypass the gate (warning printed). For emergency hotfixes only.",
    )
    chk.set_defaults(func=_cmd_check)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
