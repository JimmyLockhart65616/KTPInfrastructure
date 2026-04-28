"""ServerHandle — opaque reference to a running KTP server instance.

Boot code (docker compose, raw subprocess, remote ssh, etc.) returns one of
these. Smoke assertions consume them. Keeps assertions decoupled from how the
server got booted.
"""

from __future__ import annotations

from dataclasses import dataclass

from .rcon import RconClient, wait_until_responsive


@dataclass
class ServerHandle:
    host: str
    port: int
    rcon_password: str

    def rcon(self, command: str, *, timeout: float = 2.0) -> str:
        """Run a single rcon command. Convenience wrapper."""
        return RconClient(
            host=self.host,
            port=self.port,
            password=self.rcon_password,
            timeout=timeout,
        ).execute(command)

    def wait_ready(self, *, timeout: float = 60.0, poll_interval: float = 1.0) -> None:
        """Block until the server answers rcon. Raises RconError on timeout."""
        wait_until_responsive(
            self.host,
            self.port,
            self.rcon_password,
            overall_timeout=timeout,
            poll_interval=poll_interval,
        )
