"""Privilege-request tickets.

`users.ini` holds a PLAINTEXT PASSWORD next to every SteamID and flag string, so
this module -- and this application -- has no code path that opens that file in
either direction. A request is a row; a human applies it over SSH and marks it
applied. Anything else would turn a Discord login into a direct route to admin
rights on 24 production instances.

Two consequences fall out of that and are deliberate:

The form never collects a password. The applying admin sets one and passes it to
the grantee out of band.

The site cannot show "your current grants" from the file, because it never reads
it. What it shows is the ticket history it wrote itself, which can drift from
reality if someone edits users.ini by hand -- so APPLIED means "an admin said
they applied it", never "verified present in the file".
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


class Scope(str, Enum):
    ONE3_MODERATOR = "one3_moderator"      # .kick, requested by 1.3 admins
    KTP_ADMIN = "ktp_admin"
    SEASON_CAPTAIN = "season_captain"      # .kick + changemap, expires with the season

    @property
    def expires_with_season(self) -> bool:
        return self is Scope.SEASON_CAPTAIN

    @property
    def requester_tier(self) -> str:
        return "one3" if self is Scope.ONE3_MODERATOR else "ktp"


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
    scope: Scope
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


def may_request(tier: str, scope: Scope) -> bool:
    """KTP admins can request any scope; 1.3 admins only their own moderators."""
    if tier == "ktp":
        return True
    if tier == "one3":
        return scope is Scope.ONE3_MODERATOR
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
        if t.scope.expires_with_season
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
