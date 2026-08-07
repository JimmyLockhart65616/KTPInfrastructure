"""Privilege-request tickets.

`users.ini` holds a PLAINTEXT PASSWORD next to every SteamID and flag string, so
this module -- and this application -- has no code path that opens that file in
either direction. A request is a row; a human applies it over SSH and marks it
applied. Anything else would turn a Discord login into a direct route to admin
rights on 24 production instances.

The model mirrors what the live file actually contains, audited 2026-08-05: 52
accounts across four headings, but only two flag sets. So a request needs two
answers, not one -- the LEVEL decides the flags, the GROUP decides which heading
the line is written under. Two grants with identical power can belong to
different groups (1.3 admins and season captains are both `cl`), and the group
is what makes a postseason sweep possible.

Two consequences fall out and are deliberate:

The form never collects a password. The applying admin sets one and passes it to
the grantee out of band.

The site cannot show "your current grants" from the file, because it never reads
it. APPLIED means "an admin said they applied it", never "verified present".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Status(str, Enum):
    SUBMITTED = "submitted"
    APPROVED = "approved"          # decided, not yet on the servers
    REJECTED = "rejected"
    APPLIED = "applied"            # a human edited users.ini
    ACTIVE = "active"              # live after the nightly restart
    REVOKED = "revoked"
    EXPIRED = "expired"            # season rolled over


class Level(str, Enum):
    """The two flag sets in live use. There is deliberately no third.

    Every level includes RCON (`l`), because every one of the 52 live accounts
    has it -- there is no kick-without-restart tier in this scheme. That means
    ANY grant here also confers `.forcereset`, `.restart` and `.quit`, and the
    request form has to say so rather than implying kick is the ceiling.
    """

    KICK_RESTART = "cl"
    KICK_BAN_RESTART = "cdl"

    @property
    def flags(self) -> str:
        return self.value

    @property
    def label(self) -> str:
        return ("Kick + Restart" if self is Level.KICK_RESTART
                else "Kick + Ban + Restart")

    @property
    def grants_ban(self) -> bool:
        return self is Level.KICK_BAN_RESTART


class Group(str, Enum):
    """Which heading in users.ini the line is written under."""

    KTP_ADMIN = "ktp_admin"
    ONE3_ADMIN = "one3_admin"
    SEASON_CAPTAIN = "season_captain"

    @property
    def heading(self) -> str:
        """The literal comment heading the applying admin looks for."""
        return {
            Group.KTP_ADMIN: "KTP Kick/Ban/Restart Admins",
            Group.ONE3_ADMIN: "1.3 Discord General Admins",
            Group.SEASON_CAPTAIN: "S{season} Captains",
        }[self]

    @property
    def expires_with_season(self) -> bool:
        return self is Group.SEASON_CAPTAIN


# A ticket only ever moves forward, and only along these edges. Encoding it here
# rather than as scattered `if status ==` checks means an impossible transition
# is a rejected call, not a row in a state nothing handles.
TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.SUBMITTED: frozenset({Status.APPROVED, Status.REJECTED}),
    Status.APPROVED: frozenset({Status.APPLIED, Status.REJECTED}),
    Status.APPLIED: frozenset({Status.ACTIVE, Status.REVOKED}),
    Status.ACTIVE: frozenset({Status.REVOKED, Status.EXPIRED}),
    Status.REJECTED: frozenset(),
    Status.REVOKED: frozenset(),
    Status.EXPIRED: frozenset(),
}

TERMINAL = frozenset({Status.REJECTED, Status.REVOKED, Status.EXPIRED})


class TransitionError(Exception):
    pass


def can_transition(current: Status, target: Status) -> bool:
    return target in TRANSITIONS[current]


def transition(current: Status, target: Status) -> Status:
    if not can_transition(current, target):
        raise TransitionError(f"{current.value} -> {target.value} is not allowed")
    return target


@dataclass(frozen=True)
class Ticket:
    id: int
    level: Level
    group: Group
    steam_id: str
    display_name: str
    requested_by: str          # Discord ID
    status: Status
    season: int | None = None  # the season a captain grant was issued for

    @property
    def is_open(self) -> bool:
        return self.status not in TERMINAL

    @property
    def awaiting_human(self) -> bool:
        """Approved but not yet applied -- the queue an admin actually works."""
        return self.status is Status.APPROVED

    @property
    def heading(self) -> str:
        h = self.group.heading
        return h.format(season=self.season) if "{season}" in h else h


def may_request(tier: str, level: Level, group: Group) -> bool:
    """Who may ask for what.

    KTP admins may request anything. 1.3 admins may only add their own
    community's admins, and only at the lower level -- ban is a KTP decision,
    and letting the 1.3 tier grant it would make the split between the two
    groups meaningless.
    """
    if tier == "ktp":
        return True
    if tier == "one3":
        return group is Group.ONE3_ADMIN and level is Level.KICK_RESTART
    return False


def expiring_tickets(tickets: list[Ticket], next_season_number: int) -> list[Ticket]:
    """Captain grants that the season rollover will end.

    Matches on `season < next_season_number` rather than equality so a grant
    left over from an older season is still caught -- if a rollover is ever
    missed, the stale grants must not become invisible.
    """
    return [
        t
        for t in tickets
        if t.group.expires_with_season
        and t.status is Status.ACTIVE
        and (t.season is None or t.season < next_season_number)
    ]


def nag_banner(tickets: list[Ticket], next_season_number: int, starts: date) -> str | None:
    """Copy for the KTP-admin banner, or None when there is nothing to say."""
    due = expiring_tickets(tickets, next_season_number)
    if not due:
        return None
    noun, verb = ("grant", "expires") if len(due) == 1 else ("grants", "expire")
    return (
        f"{len(due)} captain {noun} {verb} when S{next_season_number} begins "
        f"({starts.isoformat()}). Review and revoke."
    )
