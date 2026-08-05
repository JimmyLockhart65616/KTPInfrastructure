"""Fleet status poller.

One poll for all viewers: a systemd timer runs this on the data server, it
queries the 24 instances once, and writes a small JSON the page serves as a
static file. The alternative -- querying from the browser -- would fan 24 UDP
round-trips out per visitor and expose the fleet's addressing to anyone with
devtools.

Two properties keep the page honest:

A single missed reply is NOT down. A healthy Atlanta instance timed out at 1.5s
during a sweep that returned 24/24 at 2.0s, so one miss means "slow", and only
DOWN_AFTER consecutive misses flips a server to down.

Staleness is a state, not an absence. If this poller dies, the JSON it already
wrote stays on disk and would otherwise render as a healthy fleet forever. Every
document carries `generated` and the page treats an old one as unknown.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .a2s import A2SError, count_humans, query, query_players
from .hostname import parse

DOWN_AFTER = 3          # consecutive failed polls before a server reads "down"
POLL_TIMEOUT = 2.5
MAX_WORKERS = 12


@dataclass(frozen=True)
class Instance:
    region: str
    label: str
    ip: str
    port: int


def fleet() -> list[Instance]:
    hosts = [
        ("Atlanta", "74.91.121.9", 5),
        ("Dallas", "74.91.126.55", 5),
        ("Denver", "66.163.114.109", 5),
        ("New York", "74.91.123.64", 5),
        ("Chicago", "172.238.176.101", 4),
    ]
    return [
        Instance(region, f"{region} {n + 1}", ip, 27015 + n)
        for region, ip, count in hosts
        for n in range(count)
    ]


@dataclass
class _Streak:
    misses: int = 0
    last_ok: float | None = None


_streaks: dict[str, _Streak] = {}


def _poll_one(inst: Instance) -> dict:
    key = f"{inst.ip}:{inst.port}"
    streak = _streaks.setdefault(key, _Streak())
    try:
        info = query(inst.ip, inst.port, POLL_TIMEOUT)
    except A2SError as exc:
        streak.misses += 1
        return {
            "instance": inst,
            "up": streak.misses < DOWN_AFTER,
            "degraded": True,
            "misses": streak.misses,
            "error": str(exc),
            "last_ok": streak.last_ok,
        }
    streak.misses, streak.last_ok = 0, time.time()

    # A2S's player count includes the HLTV proxy, so it never reads 0 on a live
    # instance. Ask for the roster and count actual people; if that second query
    # fails, fall back rather than losing the whole server from the page.
    try:
        humans = count_humans(query_players(inst.ip, inst.port, POLL_TIMEOUT))
    except A2SError:
        humans = None

    return {
        "instance": inst,
        "up": True,
        "degraded": False,
        "misses": 0,
        "info": info,
        "name": parse(info.hostname),
        "humans": humans,
        "last_ok": streak.last_ok,
    }


def poll_fleet(instances: list[Instance] | None = None) -> list[dict]:
    instances = instances or fleet()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        return list(pool.map(_poll_one, instances))


def public_document(results: list[dict], now: float | None = None) -> dict:
    """Build the logged-out view.

    Allowlisted by construction: this function names every field it emits, so a
    field added upstream cannot leak by default. IPs, ports, miss counts and
    error strings are fleet topology and deliberately absent.
    """
    servers = []
    for r in results:
        inst: Instance = r["instance"]
        entry = {"region": inst.region, "label": inst.label, "up": bool(r["up"])}
        if not r["degraded"]:
            info, name = r["info"], r["name"]
            entry["map"] = info.map
            # Roster count when we have it; the A2S slot count only as a fallback,
            # and that one still includes HLTV.
            humans = r.get("humans")
            entry["players"] = info.humans if humans is None else humans
            entry["max_players"] = info.max_players
            if name.match_type:
                entry["match_type"] = name.match_type
                entry["state"] = name.state
        servers.append(entry)
    up = sum(1 for s in servers if s["up"])
    return {
        "generated": int(now or time.time()),
        "servers": servers,
        "summary": {"up": up, "total": len(servers),
                    "players": sum(s.get("players", 0) for s in servers)},
    }


def detail_document(results: list[dict], now: float | None = None) -> dict:
    """Full operator view -- written outside the web root, served only to admins."""
    return {
        "generated": int(now or time.time()),
        "servers": [
            {
                "label": r["instance"].label,
                "address": f"{r['instance'].ip}:{r['instance'].port}",
                "up": bool(r["up"]),
                "degraded": bool(r["degraded"]),
                "consecutive_misses": r["misses"],
                "last_ok": r["last_ok"],
                "error": r.get("error"),
                "hostname": r["info"].hostname if not r["degraded"] else None,
            }
            for r in results
        ],
    }


def write_atomic(path: str, doc: dict) -> None:
    """Never let a reader see a half-written document."""
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, separators=(",", ":"))
        os.replace(tmp, path)
    except BaseException:
        os.path.exists(tmp) and os.unlink(tmp)
        raise
