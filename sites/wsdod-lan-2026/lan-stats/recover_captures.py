#!/usr/bin/env python3
"""Rebuild the LAN's missing capture events from the HLDS logs.

The LAN box's HLStatsX ran with an unseeded `hlstats_Actions` table, so every
`dod_control_point` / `dod_capture_area` event arrived, failed to resolve to an
action id, and was discarded. Kills and weapon stats were unaffected -- only
objectives were lost.

The events themselves survive in the servers' own HLDS logs, which is the same
source HLStatsX reads. This parses them and writes rows in exactly the shape
prod produces, so the LAN dataset ends up structurally identical to the league's
and the same queries work against both.

Deliberately NOT done by replaying the logs through HLStatsX: the daemon has no
memory of what it already ingested, so a replay would re-insert every frag and
weaponstat on top of the existing rows.

Writes to `hlstatsx_lan` on the data server -- a restored clone, never the live
league database. LAN serverIds (26-30) and playerIds overlap the fleet's.
"""

from __future__ import annotations

import re
from datetime import datetime

# Action ids mirror prod so the two datasets are directly comparable.
ACTIONS = {
    "dod_control_point": (337, "Control Points Captured"),
    "dod_capture_area": (338, "Areas Captured"),
    "dod_object_goal": (339, "Objectives Achieved"),
}
BONUS = 6              # reward_player for both capture actions in prod
PORT_TO_SERVER = {27015: 26, 27016: 27, 27017: 28, 27018: 29, 27019: 30}

TS = r"L (\d{2}/\d{2}/\d{4}) - (\d{2}:\d{2}:\d{2}):"
RE_MARK = re.compile(
    TS + r'\s+(KTP_MATCH_START|KTP_HALF_END|KTP_MATCH_END)\s+\(matchid "([^"]+)"\)'
    r'(?:\s+\(map "([^"]+)"\))?(?:\s+\(half "([^"]+)"\))?')
RE_CAP = re.compile(
    TS + r'\s+"(?P<name>.*)<\d+><(?P<steam>STEAM_\d:\d:\d+)><(?P<team>[^>]*)>"'
    r'\s+triggered a "(?P<action>dod_[a-z_]+)"(?:\s+-\s+"(?P<point>[^"]*)")?')


def when(day: str, clock: str) -> datetime:
    return datetime.strptime(day + " " + clock, "%m/%d/%Y %H:%M:%S")


def parse(path: str):
    """-> (windows, captures). Windows are per-instance match/half spans."""
    marks, caps = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            inst, _, rest = raw.partition("\t")
            try:
                port = int(inst.rsplit("-", 1)[1])
            except (IndexError, ValueError):
                continue
            m = RE_MARK.search(rest)
            if m:
                day, clock, kind, mid, mp, half = m.groups()
                marks.append({"port": port, "t": when(day, clock), "kind": kind,
                              "match_id": mid, "map": mp, "half": half})
                continue
            m = RE_CAP.search(rest)
            if m:
                d = m.groupdict()
                caps.append({"port": port, "t": when(m.group(1), m.group(2)),
                             "steam": d["steam"], "team": d["team"],
                             "action": d["action"], "point": d["point"] or ""})
    return marks, caps


def windows(marks: list[dict]) -> list[dict]:
    """Build [start, end] spans carrying match_id, map and half.

    KTP_MATCH_START fires once PER HALF and names which -- "1st half" / "2nd
    half" -- so the half is read from the marker rather than inferred from
    position. Inferring it (first start = half 1, after HALF_END = half 2) put
    5,989 of 6,015 captures in half 1, because a second START silently replaced
    the first.

    A span closes on the next boundary of any kind, so a half missing its
    HALF_END still ends at MATCH_END rather than swallowing the rest of the day.
    """
    out = []
    per_port: dict[int, list[dict]] = {}
    for m in sorted(marks, key=lambda x: (x["port"], x["t"])):
        per_port.setdefault(m["port"], []).append(m)

    for port, seq in per_port.items():
        open_span = None
        for m in seq:
            if open_span and m["kind"] in ("KTP_HALF_END", "KTP_MATCH_END", "KTP_MATCH_START"):
                out.append({**open_span, "port": port, "end": m["t"]})
                open_span = None
            if m["kind"] == "KTP_MATCH_START":
                half = 2 if (m["half"] or "").startswith("2") else 1
                open_span = {"match_id": m["match_id"], "map": m["map"],
                             "half": half, "start": m["t"]}
    return out


def attribute(caps: list[dict], spans: list[dict]) -> tuple[list[dict], list[dict]]:
    """Place each capture in its match/half. Returns (placed, orphans)."""
    by_port: dict[int, list[dict]] = {}
    for s in spans:
        by_port.setdefault(s["port"], []).append(s)
    for v in by_port.values():
        v.sort(key=lambda s: s["start"])

    placed, orphans = [], []
    for cap in caps:
        hit = None
        for s in by_port.get(cap["port"], ()):
            if s["start"] <= cap["t"] <= s["end"]:
                hit = s
                break
        if hit:
            placed.append({**cap, "match_id": hit["match_id"],
                           "map": hit["map"], "half": hit["half"]})
        else:
            orphans.append(cap)
    return placed, orphans


def steam_to_unique(steam: str) -> str:
    """STEAM_0:1:443810 -> 1:443810, the form hlstats_PlayerUniqueIds stores."""
    return steam.split(":", 1)[1]


if __name__ == "__main__":
    import json
    import sys

    src = sys.argv[1] if len(sys.argv) > 1 else "lan-log-events.tsv"
    marks, caps = parse(src)
    spans = windows(marks)
    placed, orphans = attribute(caps, spans)

    print("markers      %5d" % len(marks))
    print("spans        %5d  (matches: %d)" % (len(spans), len({s["match_id"] for s in spans})))
    print("captures     %5d" % len(caps))
    print("  placed     %5d" % len(placed))
    print("  orphaned   %5d  (outside any match window -- warmup/pubs)" % len(orphans))
    print()
    by_action: dict[str, int] = {}
    for p in placed:
        by_action[p["action"]] = by_action.get(p["action"], 0) + 1
    for k, v in sorted(by_action.items()):
        print("  %-20s %5d" % (k, v))
    print()
    halves: dict[int, int] = {}
    for p in placed:
        halves[p["half"]] = halves.get(p["half"], 0) + 1
    print("  by half:", dict(sorted(halves.items())))
    print("  distinct players:", len({p["steam"] for p in placed}))

    with open("captures-placed.json", "w", encoding="utf-8") as fh:
        json.dump([{**p, "t": p["t"].isoformat()} for p in placed], fh)
    print("\nwrote captures-placed.json")
