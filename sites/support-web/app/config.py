"""Environment-driven settings.

`os.environ.get(k, default)` is avoided throughout in favour of `or`: a key set
to the empty string returns '' rather than the default, and deployment tooling
routinely sets a variable to '' when it has no value. That pattern has already
pinned a CI run to the empty string once in this repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _ids(raw: str | None) -> set[str]:
    return {p.strip() for p in (raw or "").split(",") if p.strip()}


@dataclass(frozen=True)
class Settings:
    session_secret: str
    report_salt: str

    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str

    guild_id: str
    channel_server_reports: str
    channel_player_reports: str
    relay_url: str
    relay_secret: str

    ktp_admin_ids: set[str] = field(default_factory=set)
    one3_admin_ids: set[str] = field(default_factory=set)

    public_json: str = "/var/www/support.ktpdod.com/status/public.json"
    detail_json: str = "/var/lib/support-web/detail.json"

    @property
    def oauth_configured(self) -> bool:
        return bool(self.discord_client_id and self.discord_client_secret)

    @property
    def relay_configured(self) -> bool:
        return bool(self.relay_url and self.relay_secret)

    def channel_for(self, channel_name: str) -> str:
        return (
            self.channel_player_reports
            if channel_name == "player"
            else self.channel_server_reports
        )


def load() -> Settings:
    env = os.environ.get
    return Settings(
        session_secret=env("SUPPORT_SESSION_SECRET") or "",
        report_salt=env("SUPPORT_REPORT_SALT") or "",
        discord_client_id=env("DISCORD_CLIENT_ID") or "",
        discord_client_secret=env("DISCORD_CLIENT_SECRET") or "",
        discord_redirect_uri=env("DISCORD_REDIRECT_URI") or "",
        guild_id=env("SUPPORT_DISCORD_GUILD_ID") or "",
        channel_server_reports=env("SUPPORT_CHANNEL_SERVER_REPORTS") or "",
        channel_player_reports=env("SUPPORT_CHANNEL_PLAYER_REPORTS") or "",
        relay_url=env("DISCORD_RELAY_URL") or "",
        relay_secret=env("DISCORD_RELAY_SECRET") or "",
        ktp_admin_ids=_ids(env("SUPPORT_KTP_ADMIN_IDS")),
        one3_admin_ids=_ids(env("SUPPORT_ONE3_ADMIN_IDS")),
        public_json=env("SUPPORT_PUBLIC_JSON") or Settings.public_json,
        detail_json=env("SUPPORT_DETAIL_JSON") or Settings.detail_json,
    )


settings = load()
