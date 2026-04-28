"""Pytest fixtures + path constants for config-parse tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/config_parse/conftest.py → KTPInfrastructure/
INFRA_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = INFRA_ROOT / "config"

# Profiles that ship complete real configs (not just .example).
# Online profile holds production-critical files; LAN is a partial profile
# tested separately if/when needed.
COMPLETE_PROFILES = ("local", "online")


@pytest.fixture(scope="session")
def config_root() -> Path:
    return CONFIG_ROOT
