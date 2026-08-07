"""Discord Relay client.

Posts through the existing Cloud Run relay (`POST /reply`, `X-Relay-Auth`)
rather than holding a bot token here. One shared secret guards the relay, so
this service gets no Discord credential of its own and cannot be used to reach
Discord for anything but posting.

Failure is returned, never raised. A report is already durable in the database
before this is called, so a relay outage delays delivery -- it must not turn
into a 500 that tells the reporter their report was lost.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

TIMEOUT = 8.0

# The relay defaults allowed_mentions to {parse: []}, but this path suppresses
# explicitly: the passthrough is load-bearing for other callers (crashreporter
# @everyone, role pings), so relying on someone else's default is how a report
# body containing @everyone eventually pings the server.
NO_MENTIONS = {"parse": []}


@dataclass(frozen=True)
class RelayResult:
    ok: bool
    status: int | None = None
    error: str | None = None


def post_embed(
    url: str, secret: str, channel_id: str, embed: dict, *, timeout: float = TIMEOUT
) -> RelayResult:
    """Send one embed to one channel. Returns success rather than raising."""
    if not (url and secret and channel_id):
        return RelayResult(False, None, "relay not configured")

    payload = {
        "channelId": channel_id,
        "embeds": [embed],
        "allowed_mentions": NO_MENTIONS,
    }
    # The fleet's existing config (/etc/ktp/discord-relay.conf) stores RELAY_URL
    # with /reply already on it, while a bare base URL is the obvious thing to
    # put in an env var. Accept both rather than making one of them silently
    # POST to /reply/reply.
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/reply"):
        endpoint += "/reply"

    try:
        r = httpx.post(
            endpoint,
            json=payload,
            headers={"X-Relay-Auth": secret, "Content-Type": "application/json"},
            timeout=timeout,
        )
    except httpx.HTTPError as exc:
        return RelayResult(False, None, str(exc))
    if r.status_code >= 400:
        # Body is not surfaced to the reporter -- it can carry channel and token
        # detail. It goes to the service log for an operator.
        return RelayResult(False, r.status_code, r.text[:200])
    return RelayResult(True, r.status_code)


def report_embed(report, intake_id: str) -> dict:
    """Discord embed for a report. All user text lands in fields, never in a
    place Discord would resolve as a mention or a link preview."""
    return {
        "title": f"Report — {report.category.value.replace('_', ' ')}",
        "color": 0xE0796A if report.channel.value == "player" else 0xD9A445,
        "fields": [
            {"name": "Server", "value": report.server_label or "not specified", "inline": True},
            {"name": "Reporter", "value": report.handle or "anonymous", "inline": True},
            {"name": "Intake", "value": f"`{intake_id}`", "inline": True},
            {"name": "Details", "value": report.body[:1024], "inline": False},
        ],
    }
