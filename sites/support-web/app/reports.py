"""Report-a-problem intake: validation, routing and rate limiting.

A public unauthenticated write, so it is treated as hostile by default. Three
properties are load-bearing:

Routing is decided by the category enum, never by the submitter. If the reporter
picks the destination then both mistakes and deliberate misrouting put a
cheating accusation into a general ops room.

Nothing is ever echoed back to a public surface. There is no "recent reports"
view and no ticket-status page -- the submitter sees "sent" and any reply
happens on Discord.

The IP is hashed with a server-side salt before it is used as a bucket key. We
need dedupe and rate limiting, not a register of who reported whom.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum

MAX_BODY = 2000
MAX_HANDLE = 64
MIN_FILL_SECONDS = 3.0        # a human cannot read and complete the form faster
RATE_LIMIT = 3                # reports ...
RATE_WINDOW = 3600.0          # ... per hour, per hashed IP


class Channel(str, Enum):
    SERVER = "server"
    PLAYER = "player"


class Category(str, Enum):
    SERVER_DOWN = "server_down"
    LAG = "lag"
    CRASH = "crash"
    CONFIG = "config"
    HLTV_DEMO = "hltv_demo"
    OTHER = "other"
    PLAYER_CONDUCT = "player_conduct"
    CHEATING = "cheating"

    @property
    def channel(self) -> Channel:
        """Conduct and cheating go to the narrower room; everything else is ops."""
        return (
            Channel.PLAYER
            if self in (Category.PLAYER_CONDUCT, Category.CHEATING)
            else Channel.SERVER
        )


class ReportRejected(Exception):
    """Rejected before it reaches Discord. The message is safe to show a user."""


@dataclass(frozen=True)
class Report:
    category: Category
    server_label: str | None
    body: str
    handle: str | None

    @property
    def channel(self) -> Channel:
        return self.category.channel


def validate(
    category: str,
    body: str,
    server_label: str | None = None,
    handle: str | None = None,
    honeypot: str = "",
    elapsed: float | None = None,
    valid_labels: set[str] | None = None,
) -> Report:
    """Build a Report or raise ReportRejected. Everything here is untrusted."""
    if honeypot.strip():
        # Bots fill hidden fields. The caller returns 200 so they learn nothing.
        raise ReportRejected("dropped")
    if elapsed is not None and elapsed < MIN_FILL_SECONDS:
        raise ReportRejected("That was too quick — please try again.")

    try:
        cat = Category(category)
    except ValueError:
        raise ReportRejected("Pick a category from the list.") from None

    text = (body or "").strip()
    if not text:
        raise ReportRejected("Tell us what happened.")
    if len(text) > MAX_BODY:
        raise ReportRejected(f"Please keep it under {MAX_BODY} characters.")

    label = (server_label or "").strip() or None
    if label and valid_labels is not None and label not in valid_labels:
        # Free-text server names would be an injection vector into the embed.
        raise ReportRejected("Pick a server from the list.")

    who = (handle or "").strip() or None
    if who and len(who) > MAX_HANDLE:
        raise ReportRejected("That Discord handle is too long.")

    return Report(cat, label, text, who)


@dataclass
class RateLimiter:
    """Fixed-window bucket keyed on a salted IP hash.

    Deliberately in-process: one poller, one app, small community. If the app is
    ever run multi-worker this must move to the database, or each worker will
    grant the full allowance independently.
    """

    limit: int = RATE_LIMIT
    window: float = RATE_WINDOW
    _hits: dict[str, list[float]] = field(default_factory=dict)

    @staticmethod
    def key(ip: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()[:32]

    def check(self, key: str, now: float | None = None) -> bool:
        """True if this key may submit now. Records the hit when it returns True."""
        now = time.time() if now is None else now
        recent = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        recent = [t for t in self._hits.get(key, []) if now - t < self.window]
        if len(recent) < self.limit:
            return 0
        return max(1, int(self.window - (now - min(recent))))

    def prune(self, now: float | None = None) -> None:
        """Drop expired buckets so the dict cannot grow without bound."""
        now = time.time() if now is None else now
        self._hits = {
            k: keep
            for k, v in self._hits.items()
            if (keep := [t for t in v if now - t < self.window])
        }


def embed_fields(report: Report, intake_id: str) -> dict:
    """Relay payload. User text goes in fields, never in a mention-capable slot."""
    return {
        "title": f"Report — {report.category.value.replace('_', ' ')}",
        "fields": [
            {"name": "Server", "value": report.server_label or "not specified"},
            {"name": "Reporter", "value": report.handle or "anonymous"},
            {"name": "Details", "value": report.body[:1024]},
            {"name": "Intake", "value": intake_id},
        ],
        # The relay's mention passthrough is load-bearing elsewhere, so this path
        # must suppress it explicitly rather than assume it is off.
        "allowed_mentions": {"parse": []},
    }
