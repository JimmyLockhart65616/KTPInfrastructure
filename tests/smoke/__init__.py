"""KTP Tier 1 smoke-test harness.

Public surface:
- ServerHandle, RconClient, RconError, RconAuthError
- compose_up, compose_down, compose_logs, booted
- assert_modules_loaded, assert_plugins_running

See README.md for usage.
"""

from .rcon import RconAuthError, RconClient, RconError, wait_until_responsive
from .server_handle import ServerHandle

__all__ = [
    "RconAuthError",
    "RconClient",
    "RconError",
    "ServerHandle",
    "wait_until_responsive",
]
