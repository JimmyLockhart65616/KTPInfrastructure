"""Catch the modules.ini regression class.

Examples this catches:
- Typo in a module name (`amxxxcurl` instead of `amxxcurl` → module won't load,
  cascades ALL plugins relying on `ktp_discord.inc` into bad-load — same shape
  as the 2026-04-14 incident, caught one tier earlier than smoke)
- Module referenced by name that doesn't ship with KTPAMXX
- Duplicate entries
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import COMPLETE_PROFILES, CONFIG_ROOT
from .parsers import parse_modules_ini

# Modules that ship with the KTPAMXX build. Order: KTPAMXX core (fun, engine,
# fakemeta, hamsandwich) + KTP-specific (dodx, reapi, amxxcurl) + supporting
# (sqlite, sockets, regex, json, geoip, nvault).
KNOWN_MODULES: set[str] = {
    # KTPAMXX core
    "fun",
    "engine",
    "fakemeta",
    "hamsandwich",
    # KTP-specific
    "dodx",
    "reapi",
    "amxxcurl",
    # Supporting (optional in any given profile)
    "sqlite",
    "sockets",
    "regex",
    "json",
    "geoip",
    "nvault",
}


@pytest.fixture(params=COMPLETE_PROFILES)
def modules_ini(request) -> Path:
    return CONFIG_ROOT / request.param / "modules.ini"


def test_modules_ini_parses(modules_ini):
    names = parse_modules_ini(modules_ini)
    assert names, f"{modules_ini} produced no module entries"


def test_no_duplicate_modules(modules_ini):
    names = parse_modules_ini(modules_ini)
    seen: dict[str, int] = {}
    for i, n in enumerate(names, 1):
        if n in seen:
            pytest.fail(f"{modules_ini.name}: duplicate module {n!r}")
        seen[n] = i


def test_all_modules_known(modules_ini):
    names = parse_modules_ini(modules_ini)
    unknown = [n for n in names if n not in KNOWN_MODULES]
    if unknown:
        pytest.fail(
            f"{modules_ini.name} references unknown module(s): {unknown}\n"
            "If a new module was added to KTPAMXX, update KNOWN_MODULES."
        )


def test_required_modules_present(modules_ini):
    """KTP plugins universally depend on dodx + reapi + amxxcurl. Stripping
    any of them makes the entire plugin fleet 'bad load' — same blast radius
    as the 04-14 incident."""
    names = set(parse_modules_ini(modules_ini))
    missing = {"dodx", "reapi", "amxxcurl"} - names
    assert not missing, f"{modules_ini.name} missing required modules: {sorted(missing)}"
