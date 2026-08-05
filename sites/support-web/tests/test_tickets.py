"""Ticket state machine and privilege-scope tests.

The transition tests are the guard on the whole users.ini design: SUBMITTED must
never reach APPLIED without a human APPROVING it, and a terminal ticket must
never come back to life.
"""

from datetime import date

import pytest

from app.tickets import (
    TERMINAL,
    Scope,
    Status,
    Ticket,
    TransitionError,
    can_transition,
    expiring_tickets,
    may_request,
    nag_banner,
    transition,
)


def t(status=Status.ACTIVE, scope=Scope.SEASON_CAPTAIN, season=10, tid=1):
    return Ticket(tid, scope, "STEAM_0:1:1", "someone", "discord:1", status, season)


# --- the state machine ---------------------------------------------------

def test_a_request_cannot_skip_human_approval():
    assert not can_transition(Status.SUBMITTED, Status.APPLIED)
    assert not can_transition(Status.SUBMITTED, Status.ACTIVE)
    with pytest.raises(TransitionError):
        transition(Status.SUBMITTED, Status.APPLIED)


def test_the_happy_path_walks_all_four_steps():
    s = Status.SUBMITTED
    for nxt in (Status.APPROVED, Status.APPLIED, Status.ACTIVE):
        s = transition(s, nxt)
    assert s is Status.ACTIVE


@pytest.mark.parametrize("dead", sorted(TERMINAL, key=lambda s: s.value))
def test_terminal_states_are_terminal(dead):
    for target in Status:
        assert not can_transition(dead, target)


def test_approved_can_still_be_rejected_before_it_is_applied():
    assert can_transition(Status.APPROVED, Status.REJECTED)
    # ...but not after, because the grant is on the servers by then.
    assert not can_transition(Status.APPLIED, Status.REJECTED)
    assert can_transition(Status.APPLIED, Status.REVOKED)


def test_every_status_has_a_transition_rule():
    # A status added without an entry would KeyError at runtime, in the middle
    # of an admin action rather than at import.
    for s in Status:
        assert s in can_transition.__globals__["TRANSITIONS"]


def test_open_and_awaiting_human_mean_what_they_say():
    assert t(Status.SUBMITTED).is_open and not t(Status.SUBMITTED).awaiting_human
    assert t(Status.APPROVED).awaiting_human
    assert not t(Status.REVOKED).is_open


# --- who may request what ------------------------------------------------

def test_one3_admins_can_only_request_their_own_moderators():
    assert may_request("one3", Scope.ONE3_MODERATOR)
    assert not may_request("one3", Scope.KTP_ADMIN)
    assert not may_request("one3", Scope.SEASON_CAPTAIN)


def test_ktp_admins_may_request_any_scope():
    assert all(may_request("ktp", s) for s in Scope)


@pytest.mark.parametrize("tier", ["public", "", "anonymous", "One3", "KTP"])
def test_unknown_or_miscased_tiers_get_nothing(tier):
    assert not any(may_request(tier, s) for s in Scope)


# --- season expiry -------------------------------------------------------

def test_only_active_captain_grants_expire():
    tickets = [
        t(Status.ACTIVE, Scope.SEASON_CAPTAIN, 10, 1),
        t(Status.ACTIVE, Scope.KTP_ADMIN, 10, 2),         # not season-scoped
        t(Status.REVOKED, Scope.SEASON_CAPTAIN, 10, 3),   # already gone
    ]
    assert [x.id for x in expiring_tickets(tickets, 11)] == [1]


def test_grants_from_older_seasons_are_still_caught():
    # A missed rollover must not make stale grants invisible.
    tickets = [t(season=8, tid=1), t(season=10, tid=2), t(season=None, tid=3)]
    assert {x.id for x in expiring_tickets(tickets, 11)} == {1, 2, 3}


def test_grants_for_the_upcoming_season_do_not_expire():
    assert expiring_tickets([t(season=11)], 11) == []


def test_banner_is_silent_with_nothing_due():
    assert nag_banner([], 11, date(2027, 2, 21)) is None
    assert nag_banner([t(Status.REVOKED)], 11, date(2027, 2, 21)) is None


def test_banner_names_the_count_and_the_date():
    msg = nag_banner([t(tid=1), t(tid=2)], 11, date(2027, 2, 21))
    assert "2 captain grants" in msg and "S11" in msg and "2027-02-21" in msg


def test_banner_singular_reads_correctly():
    assert "1 captain grant expires" in nag_banner([t()], 11, date(2027, 2, 21))
    assert "grants" not in nag_banner([t()], 11, date(2027, 2, 21))
