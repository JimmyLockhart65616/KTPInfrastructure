"""Best-effort Discord notifications: DMs to team captains (e.g. "you're up on
Server 3") and announcement cross-posts to a channel webhook.

DMs use a bot token (LAN_DISCORD_BOT_TOKEN) — the bot must share a guild with the
captain, which KTPAdminBot already does. No token set → silently no-ops. Network
or API failures are swallowed: a notification must never break a staff action."""
from __future__ import annotations

import json
import urllib.request

from .config import settings

_API = "https://discord.com/api/v10"
_UA = "KTP-LAN/1.0 (+https://wsdod)"


def _post(path: str, token: str, payload: dict) -> dict:
    req = urllib.request.Request(
        _API + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": _UA,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=6) as r:
        return json.loads(r.read().decode() or "{}")


def _dm(discord_id, content: str, token: str) -> None:
    chan = _post("/users/@me/channels", token, {"recipient_id": str(discord_id)})
    _post(f"/channels/{chan['id']}/messages", token, {"content": content})


def post_announcement(text: str) -> bool:
    """Cross-post the site-wide announcement to the Discord webhook. Returns True
    on delivery, False if unconfigured or the post failed. Never raises.

    allowed_mentions is pinned to the announce role alone, so staff text can never
    ping @everyone/@here by accident — the role ping is the only one that fires."""
    url = settings.discord_webhook_url
    if not url or not text:
        return False
    # A non-numeric id would 400 the whole post; degrade to no ping instead, so
    # "ROLE_ID=none" behaves like the documented empty off-switch.
    role = (settings.discord_announce_role_id or "").strip()
    if not role.isdigit():
        role = ""
    prefix = f"<@&{role}> " if role else ""
    payload = {
        "content": f"{prefix}\U0001f4e3 **ANNOUNCEMENT** — {text}",
        "allowed_mentions": {"parse": [], "roles": [role] if role else []},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": _UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6):
            return True
    except Exception:
        return False


def notify_captains(team_ids, content: str) -> int:
    """DM each given team's captain. Returns how many were sent. Never raises."""
    token = settings.discord_bot_token
    if not token:
        return 0
    from . import db
    sent = 0
    for tid in team_ids:
        if not tid:
            continue
        try:
            cap = db.query_one(
                "SELECT discord_id FROM lan_players "
                "WHERE team_id=%s AND is_captain=1 AND discord_id IS NOT NULL LIMIT 1",
                (tid,),
            )
            if cap and cap["discord_id"]:
                _dm(cap["discord_id"], content, token)
                sent += 1
        except Exception:
            pass  # best-effort; never let a DM failure surface to the admin
    return sent
