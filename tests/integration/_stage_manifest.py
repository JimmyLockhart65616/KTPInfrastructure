"""Resolve "which build is the runner holding?" from the stage manifest.

The version pin used to be a literal in each test (`... or "0.10.147"`), bumped
by hand as a checklist step. It rotted on 2026-08-03: the runner sat two
versions behind the artifact about to be waved and every behaviour test still
passed, because the pin was the only thing that could have caught it.

`scripts/stage-runner.py` now records what it staged, so the pin can come from
the act of staging instead of from someone remembering. Resolution order:

  1. env override  — the pre-activation gate, where the runner deliberately
                     LEADS the fleet and the version under test is not yet the
                     version anywhere else. Must win.
  2. manifest      — what stage-runner.py last put on this runner.
  3. literal floor — kept so a runner with no manifest yet (or a workstation
                     running the suite by hand) still asserts *something*
                     rather than silently skipping the check.

The version cannot be read out of the compiled `.amxx` (XXMA+zlib), which is
why the stager has to write it down and the test cannot just discover it.
"""

from __future__ import annotations

import json
import os
import posixpath
from pathlib import Path

_TREE = os.environ.get("KTP_TIER2_TREE", "/opt/ktp-tier2-runner/serverfiles")
_DEFAULT_MANIFEST = posixpath.join(posixpath.dirname(_TREE), "stage-manifest.json")


def _load() -> dict:
    path = os.environ.get("KTP_TIER2_MANIFEST", _DEFAULT_MANIFEST)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # Absent or unreadable is normal off-runner; a corrupt manifest must not
        # take the suite down, it just falls through to the literal floor.
        return {}
    return data if isinstance(data, dict) else {}


def expected_version(plugin_basename: str, env_var: str, floor: str) -> str:
    """Pin for `plugin_basename`, honouring the env override first.

    `or` not a get() default, deliberately: the workflow always SETS the env var,
    to '' on scheduled and PR runs, and `os.environ.get(k, default)` returns ''
    for a set-but-empty var — which would pin every non-gate run to the empty
    string and fail all of them.
    """
    override = os.environ.get(env_var) or ""
    if override:
        return override
    entry = _load().get(plugin_basename) or {}
    return entry.get("version") or floor


def staged_md5(plugin_basename: str) -> str | None:
    """md5 stage-runner.py recorded for this plugin, or None if unrecorded."""
    return (_load().get(plugin_basename) or {}).get("md5")


def source() -> str:
    """Where a pin came from — for test failure messages, so a drift failure
    says whether it is arguing with the manifest or with a hardcoded floor."""
    path = os.environ.get("KTP_TIER2_MANIFEST", _DEFAULT_MANIFEST)
    return path if Path(path).exists() else "(no manifest — using literal floor)"
