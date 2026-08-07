"""Serving the poller's output, with staleness treated as a state.

The poller writes `public.json` and stops touching it if it dies. Without this
module a dead poller would render a green fleet forever, which is the worst
possible failure for a status page -- confidently wrong beats nothing only if it
is right. An old document is reported as UNKNOWN, not as healthy.
"""

from __future__ import annotations

import json
import time
from enum import Enum

# The poller fires every 60s. Two missed runs is noise; four means something is
# actually wrong, and that is when the page should stop asserting.
STALE_AFTER = 240
MISSING = "status is unavailable right now"


class Freshness(str, Enum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


def freshness(doc: dict | None, now: float | None = None) -> Freshness:
    if not doc or "generated" not in doc:
        return Freshness.MISSING
    age = (time.time() if now is None else now) - doc["generated"]
    return Freshness.FRESH if age <= STALE_AFTER else Freshness.STALE


def load(path: str) -> dict | None:
    """Read a status document, tolerating every way it can be unreadable.

    A half-written or corrupt file must read as "unknown", never raise: the
    poller writes atomically so this should not happen, but a status page that
    500s when its data source hiccups defeats its own purpose.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def view(doc: dict | None, now: float | None = None) -> dict:
    """What the template renders. Never raises, always answers."""
    state = freshness(doc, now)
    if state is not Freshness.FRESH:
        # Servers are dropped rather than shown greyed out. A stale list still
        # looks like a list, and someone will read player counts off it.
        return {
            "freshness": state.value,
            "servers": [],
            "by_region": [],
            "live_matches": [],
            "age": None,
            "summary": None,
            "message": MISSING,
            "generated": (doc or {}).get("generated"),
        }
    servers = doc.get("servers", [])
    return {
        "freshness": state.value,
        "servers": servers,
        "by_region": _by_region(servers),
        "live_matches": [s for s in servers if s.get("state")],
        "summary": doc.get("summary"),
        "message": None,
        "generated": doc["generated"],
        "age": _age(doc["generated"], now),
    }


def _by_region(servers: list[dict]) -> list[tuple[str, list[dict]]]:
    """Regions in first-seen order -- the poller emits them geographically, and
    re-sorting alphabetically would scatter the fleet's own grouping."""
    order: list[str] = []
    grouped: dict[str, list[dict]] = {}
    for s in servers:
        region = s.get("region", "Other")
        if region not in grouped:
            order.append(region)
            grouped[region] = []
        grouped[region].append(s)
    return [(r, grouped[r]) for r in order]


def _age(generated: int, now: float | None = None) -> str:
    secs = int((time.time() if now is None else now) - generated)
    if secs < 90:
        return f"{max(secs, 0)}s ago"
    return f"{secs // 60}m ago"


def server_labels(doc: dict | None) -> set[str]:
    """Valid `server` values for the report form -- free text would be an
    injection vector into the Discord embed."""
    return {s["label"] for s in (doc or {}).get("servers", []) if "label" in s}
