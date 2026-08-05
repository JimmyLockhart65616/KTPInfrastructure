"""KTP season calendar.

The league publishes a framework rather than dates: Spring starts the Sunday
after Super Bowl Sunday, Fall the Sunday after Labor Day, each running up to 12
match Sundays with one BYE (Easter / Thanksgiving week). That is computable, so
seasons are derived here instead of maintained in a table nobody remembers to
update.

Two properties are deliberate and load-bearing:

Season END is not derived. The framework commits to a window, explicitly not to
a fixed number of regular-season weeks, so `window_end` is the last date a
season *could* use. Anything user-facing anchors on the NEXT season's start.

Super Bowl Sunday is the one anchor that is not law or computus -- the NFL sets
it, and an 18-game season would move it. `SUPER_BOWL_OVERRIDES` exists so a
schedule change is a one-line edit rather than a silently wrong Spring.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

SPRING, FALL = "spring", "fall"

# Anchor: Fall 2026 is Season 10. Everything else counts from here.
_ANCHOR_ORDINAL, _ANCHOR_NUMBER = 2026 * 2 + 1, 10

# Year -> actual Super Bowl Sunday, when it is not the 2nd Sunday in February.
SUPER_BOWL_OVERRIDES: dict[int, date] = {}

MATCH_SUNDAYS = 12
NAG_LEAD_DAYS = 14


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th `weekday` (Mon=0) of a month."""
    d = date(year, month, 1)
    d += timedelta((weekday - d.weekday()) % 7)
    return d + timedelta(7 * (n - 1))


def easter(year: int) -> date:
    """Anonymous Gregorian computus."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b - (b - (b + 8) // 25 + 1) // 3 - d + 15 + 19 * a) % 30
    i, k = divmod(c, 4)
    g = (32 + 2 * e + 2 * i - f - k) % 7
    h = (a + 11 * f + 22 * g) // 451
    month, day = divmod(f + g - 7 * h + 114, 31)
    return date(year, month, day + 1)


def super_bowl_sunday(year: int) -> date:
    return SUPER_BOWL_OVERRIDES.get(year) or _nth_weekday(year, 2, 6, 2)


def labor_day(year: int) -> date:
    return _nth_weekday(year, 9, 0, 1)


def thanksgiving(year: int) -> date:
    return _nth_weekday(year, 11, 3, 4)


def season_start(year: int, term: str) -> date:
    if term == SPRING:
        return super_bowl_sunday(year) + timedelta(7)
    if term == FALL:
        return labor_day(year) + timedelta(6)
    raise ValueError(f"unknown term: {term!r}")


def bye_sunday(year: int, term: str) -> date:
    """Spring skips Easter; Fall skips the Sunday of Thanksgiving week."""
    return easter(year) if term == SPRING else thanksgiving(year) - timedelta(4)


def season_number(year: int, term: str) -> int:
    return _ANCHOR_NUMBER + (year * 2 + (term == FALL)) - _ANCHOR_ORDINAL


@dataclass(frozen=True)
class Season:
    number: int
    year: int
    term: str
    start: date
    bye: date
    window_end: date

    @property
    def label(self) -> str:
        return f"S{self.number}"

    @property
    def long_label(self) -> str:
        return f"S{self.number} ({self.term.title()} {self.year})"

    def match_sundays(self) -> list[date]:
        """The <=12 playable Sundays, BYE excluded."""
        days = (self.start + timedelta(7 * i) for i in range(MATCH_SUNDAYS + 1))
        return [d for d in days if d != self.bye][:MATCH_SUNDAYS]


def _build(year: int, term: str) -> Season:
    start, bye = season_start(year, term), bye_sunday(year, term)
    days = [start + timedelta(7 * i) for i in range(MATCH_SUNDAYS + 1)]
    playable = [d for d in days if d != bye][:MATCH_SUNDAYS]
    return Season(season_number(year, term), year, term, start, bye, playable[-1])


def _ordered(year: int) -> list[Season]:
    return [_build(year, SPRING), _build(year, FALL)]


def current_season(today: date) -> Season:
    """The season whose window contains `today`, else the most recent to start.

    Between windows this returns the season that just ended rather than None --
    a captain granted rights in S10 still holds them in the gap before S11, so
    "no current season" would make expiry logic answer the wrong question.
    """
    candidates = [s for s in _ordered(today.year - 1) + _ordered(today.year) if s.start <= today]
    return max(candidates, key=lambda s: s.start)


def next_season(today: date) -> Season:
    upcoming = [s for s in _ordered(today.year) + _ordered(today.year + 1) if s.start > today]
    return min(upcoming, key=lambda s: s.start)


def days_until_next_season(today: date) -> int:
    return (next_season(today).start - today).days


def should_nag(today: date, lead_days: int = NAG_LEAD_DAYS) -> bool:
    """Whether to surface the captain-expiry banner."""
    return days_until_next_season(today) <= lead_days
