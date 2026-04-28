"""dodserver.cfg — Source-engine cvar config. Catches missing critical cvars
and dangerous values (e.g. an empty rcon_password leaving production servers
exposed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import CONFIG_ROOT
from .parsers import parse_dodserver_cfg

# Online profile ships dodserver.cfg.example only — actual prod cfg is
# .gitignore'd because it carries the real rcon password. Test the example
# file as the prod-shape source of truth, and the local cfg as the dev-shape
# source of truth.
PROFILE_FILES: list[tuple[str, Path]] = [
    ("local", CONFIG_ROOT / "local" / "dodserver.cfg"),
    ("online_example", CONFIG_ROOT / "online" / "dodserver.cfg.example"),
]


@pytest.fixture(params=PROFILE_FILES, ids=[p[0] for p in PROFILE_FILES])
def cfg_path(request) -> Path:
    label, path = request.param
    if not path.exists():
        pytest.skip(f"{label}: {path} not present")
    return path


def test_dodserver_cfg_parses(cfg_path):
    cvars = parse_dodserver_cfg(cfg_path)
    assert cvars, f"{cfg_path} produced no cvar entries"


def test_required_cvars_present(cfg_path):
    """Critical cvars that production servers depend on. Missing any of
    these silently changes server behaviour. sv_lan is intentionally NOT in
    this set — online profile omits it (defaults to 0 = production); local
    profile sets it explicitly to 1. Tested separately per profile."""
    cvars = parse_dodserver_cfg(cfg_path)
    required = {"hostname", "rcon_password", "mp_timelimit", "sys_ticrate"}
    missing = required - set(cvars.keys())
    assert not missing, f"{cfg_path.name} missing required cvars: {sorted(missing)}"


def test_local_profile_has_lan_mode():
    cvars = parse_dodserver_cfg(CONFIG_ROOT / "local" / "dodserver.cfg")
    assert cvars["sv_lan"] == "1", (
        f"local/dodserver.cfg should set sv_lan 1 (Steam auth disabled for "
        f"local dev), got {cvars['sv_lan']!r}"
    )


def test_online_example_has_production_shape():
    """The online example file documents the prod cfg shape. It MUST set
    sv_lan 0 (production servers want Steam auth) and have a non-empty
    rcon_password placeholder so operators know to fill it in."""
    example = CONFIG_ROOT / "online" / "dodserver.cfg.example"
    if not example.exists():
        pytest.skip("online/dodserver.cfg.example not present")
    cvars = parse_dodserver_cfg(example)
    assert cvars.get("sv_lan") in {"0", None}, (
        f"online/dodserver.cfg.example: sv_lan should be 0 or unset for production, "
        f"got {cvars.get('sv_lan')!r}"
    )
    rcon = cvars.get("rcon_password", "")
    assert rcon, (
        "online/dodserver.cfg.example: rcon_password must be set "
        "(can be a placeholder like CHANGEME, but not empty)"
    )


def test_sys_ticrate_is_1000(cfg_path):
    """KTP fleet runs sys_ticrate 1000 — verified in CLAUDE.md and
    KTPReHLDS Host_FilterTime fix. Anything else silently caps server FPS."""
    cvars = parse_dodserver_cfg(cfg_path)
    assert cvars["sys_ticrate"] == "1000", (
        f"{cfg_path.name}: sys_ticrate should be 1000 (KTP fleet standard), "
        f"got {cvars['sys_ticrate']!r}"
    )
