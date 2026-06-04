"""iCalendar (.ics) feeds for the schedule and per-team match lists.

Times are emitted as floating local time (no TZID) — every attendee is in the
room, so the venue's wall clock is the right reference. Event dates are the LAN
weekend: Saturday group stage 1 Aug 2026, Sunday playoffs 2 Aug 2026."""
from __future__ import annotations

from datetime import datetime

from . import bracket as bkt
from . import schedule as sched

SAT_DATE = "20260801"
SUN_DATE = "20260802"
_STAMP = "20260601T000000Z"
LOC = "TAP Esport Center, Philadelphia"


def _esc(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _dt(date: str, hhmm: str) -> str:
    h, m = hhmm.split(":")
    return f"{date}T{int(h):02d}{int(m):02d}00"


def _to24(label: str) -> str:
    """'1:30 PM' -> '13:30'."""
    return datetime.strptime(label.strip(), "%I:%M %p").strftime("%H:%M")


def _plus(hhmm: str, hours: float) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    total = h * 60 + m + int(round(hours * 60))
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def _event(uid: str, start: str, end: str, summary: str, location: str = LOC, desc: str = "") -> list[str]:
    out = ["BEGIN:VEVENT", f"UID:{uid}@wsdod-lan", f"DTSTAMP:{_STAMP}",
           f"DTSTART:{start}", f"DTEND:{end}", f"SUMMARY:{_esc(summary)}"]
    if desc:
        out.append(f"DESCRIPTION:{_esc(desc)}")
    if location:
        out.append(f"LOCATION:{_esc(location)}")
    out.append("END:VEVENT")
    return out


def _wrap(name: str, events: list[str]) -> str:
    head = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//WSDoD//LAN 2026//EN",
            "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{_esc(name)}"]
    return "\r\n".join(head + events + ["END:VCALENDAR"]) + "\r\n"


def _sat_round_times() -> dict[int, tuple[str, str]]:
    """Group round -> (start24, end24) parsed from the Saturday timetable."""
    out, n = {}, 0
    for slot, _label, kind in sched.SATURDAY_TIMETABLE:
        if kind == "round":
            n += 1
            a, b = [p.strip() for p in slot.replace("–", "-").split("-")]
            out[n] = (a, b)
    return out


def _sun_dur(best_of: int) -> float:
    return 3.0 if best_of and best_of >= 5 else 2.5


# Sunday playoff milestones for the overview feed: (start, hours, label).
SUN_BLOCKS = [
    ("10:00 AM", 2.5, "QF / Play-ins"),
    ("12:30 PM", 2.5, "Semifinals / Lower R2"),
    ("3:00 PM", 2.5, "Upper Final / Lower R3"),
    ("5:30 PM", 1.0, "Lower Semifinal"),
    ("6:30 PM", 2.5, "Lower Final"),
    ("9:00 PM", 2.5, "Grand Final"),
]


def schedule_feed() -> str:
    """One event per Saturday round + per Sunday playoff milestone — overview."""
    ev: list[str] = []
    sat = _sat_round_times()
    for n, (a, b) in sat.items():
        ev += _event(f"sat-r{n}", _dt(SAT_DATE, a), _dt(SAT_DATE, b),
                     f"LAN Saturday — Round {n} (group)")
    for i, (start_label, dur, name) in enumerate(SUN_BLOCKS, 1):
        start = _to24(start_label)
        ev += _event(f"sun-b{i}", _dt(SUN_DATE, start), _dt(SUN_DATE, _plus(start, dur)),
                     f"LAN Sunday — {name}")
    return _wrap("WSDoD LAN 2026 — Schedule", ev)


def team_feed(team_id: int, team_name: str) -> str:
    """Per-match events for one team across both days."""
    ev: list[str] = []
    sat = _sat_round_times()
    for m in sched.team_schedule(team_id):
        rng = sat.get(m["round"])
        if not rng:
            continue
        opp = m.get("opponent") or "TBD"
        where = f"Server {m['station']}" if m.get("station") else LOC
        ev += _event(f"team{team_id}-sat-r{m['round']}", _dt(SAT_DATE, rng[0]), _dt(SAT_DATE, rng[1]),
                     f"{team_name} vs {opp} — R{m['round']}", where,
                     m.get("map") or "")
    for m in bkt.team_bracket(team_id):
        if not m.get("time"):
            continue
        start = _to24(m["time"])
        dur = _sun_dur(m.get("best_of"))
        opp = m.get("opponent") or "TBD"
        where = f"Server {m['station']}" if m.get("station") else LOC
        ev += _event(f"team{team_id}-{_esc(m['label'])}", _dt(SUN_DATE, start), _dt(SUN_DATE, _plus(start, dur)),
                     f"{team_name} — {m['label']} vs {opp}", where, m.get("map") or "")
    return _wrap(f"WSDoD LAN 2026 — {team_name}", ev)
