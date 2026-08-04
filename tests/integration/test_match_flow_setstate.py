"""`.setstate` — direct match half/score override (KTPMatchHandler 0.10.150+).

`.setstate` is the recovery tool for a match whose state machine lost track of
reality: halftime context lost, state re-grafted onto a fresh `.ktp`, scores
diverged from the scoreboard. An admin types the current truth and the plugin
adopts it.

It shipped in 0.10.148 and was, until 0.10.150, the only KTPMatchHandler command
with no automated coverage at all — it is chat-only, and the Tier-2 harness has
no connected-client capability (DoD ships no bot AI, so `addbot` produces a slot
with nobody in it). 0.10.150 added `amx_ktp_test_setstate`, which runs the same
`setstate_gate_reason()` and `setstate_validate_scores()` the chat command runs
and skips only chat-arg tokenizing and the retype-to-confirm window.

## The score model, because it is the whole risk surface

  - `allies` / `axis` are CURRENT CUMULATIVE scoreboard totals, by SIDE.
  - `h1_team1` / `h1_team2` are 1st-half scores by TEAM IDENTITY.
  - Team1 started the match as Allies, team2 as Axis. **Sides swap at
    halftime.** So in half 2, team1 is playing Axis:

        team1_h2 = axis   - h1_team1
        team2_h2 = allies - h1_team2

Every test below uses four mutually distinct numbers so a swapped derivation
cannot coincidentally satisfy an assertion.

⚠️ `MatchState.score_team1` / `.score_team2` are misnamed for this purpose: they
read `g_matchScore[1]` / `g_matchScore[2]`, which are indexed **by side**
(1=Allies, 2=Axis), not by team identity. Asserting `score_team1 == h1_team1`
would therefore be wrong in half 2 and right in half 1 — for the wrong reason.
These tests always compare them against `allies` / `axis`.

## Cross-references

  - `KTPMatchHandler.sma` — `cmd_setstate`, `execute_setstate`,
    `setstate_gate_reason`, `setstate_validate_scores`
  - `tests/integration/match_flow.py` — `MatchDriver.setstate`, `SetStateResult`
  - CHANGELOG.md § 0.10.150
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from .match_flow import MatchDriver, MatchType


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


@pytest.fixture()
def live_h2(hlds):
    """A live COMPETITIVE match sitting in the 2nd half — the state `.setstate`
    is nearly always reached from in production. Torn down to idle so a failure
    mid-test cannot leak a live match into the next test."""
    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    driver.advance_live(half=1)
    driver.end_first_half(score_team1=3, score_team2=2)
    driver.advance_live(half=2)
    yield driver
    driver.reset()


# ---------------------------------------------------------------------------
# Acceptance — the arithmetic
# ---------------------------------------------------------------------------

def test_setstate_half2_derives_swapped_second_half(live_h2):
    """The load-bearing case: in half 2, team1's 2nd-half score comes from the
    AXIS total and team2's from the ALLIES total, because sides swapped.

    Numbers chosen so every derived value is distinct and no transposition
    produces the same pair:

        allies=8 axis=5 h1_team1=3 h1_team2=2
        team1_h2 = 5 - 3 = 2
        team2_h2 = 8 - 2 = 6

    A non-swapped implementation would derive (8-3, 5-2) = (5, 3) — different
    in both slots, so this assertion catches it.
    """
    result = live_h2.setstate(half=2, allies=8, axis=5, h1_team1=3, h1_team2=2)

    assert result.accepted, f"setstate rejected unexpectedly: {result.reason}"
    assert result.derived_h2 == (2, 6), (
        f"2nd-half derivation wrong: got {result.derived_h2}, expected (2, 6). "
        f"(5-3, 8-2) is the swapped-sides answer; (5, 3) would mean the swap "
        f"was not applied."
    )

    state = live_h2.get_state()
    assert state.current_half == 2
    # score_team1/2 are by SIDE — see module docstring.
    assert (state.score_team1, state.score_team2) == (8, 5), (
        f"scoreboard totals not adopted: got Allies {state.score_team1} - "
        f"{state.score_team2} Axis, expected 8 - 5"
    )


def test_setstate_half1_accepts_matching_totals(live_h2):
    """In half 1 the cumulative totals ARE the 1st-half scores, so the plugin
    requires the two pairs to agree and derives no 2nd-half split."""
    result = live_h2.setstate(half=1, allies=4, axis=1, h1_team1=4, h1_team2=1)

    assert result.accepted, f"setstate rejected unexpectedly: {result.reason}"
    assert result.derived_h2 == (0, 0), (
        f"half 1 should derive no 2nd-half scores, got {result.derived_h2}"
    )

    state = live_h2.get_state()
    assert state.current_half == 1
    assert (state.score_team1, state.score_team2) == (4, 1)


# ---------------------------------------------------------------------------
# Acceptance — localinfo persistence
# ---------------------------------------------------------------------------

def test_setstate_persists_first_half_scores_to_localinfo(live_h2):
    """`_ktp_h1` carries the 1st-half split across a map change. If setstate
    adopts new H1 scores without writing them here, the next map load restores
    the OLD split and silently re-corrupts the state setstate just repaired.
    """
    assert live_h2.setstate(half=2, allies=9, axis=6, h1_team1=4, h1_team2=1).accepted

    assert live_h2.get_localinfo("_ktp_h1") == "4,1", (
        f"_ktp_h1 not updated to the setstate H1 split; got "
        f"{live_h2.get_localinfo('_ktp_h1')!r}, expected '4,1'"
    )


def test_setstate_half1_clears_stale_second_half_localinfo(live_h2):
    """A half-1 setstate must CLEAR `_ktp_h2`, not leave the previous value.

    `_ktp_h2` is how the map-load restore path distinguishes "1st half ended,
    loading for the 2nd" from "2nd half ended, map cycled back" — a non-empty
    value means the latter, i.e. a finished match. Rewinding to half 1 while a
    stale `_ktp_h2` sits in localinfo would make the next map load finalize a
    match that is still being played.

    Sequenced rather than asserted on a fresh server precisely so the clear is
    proven to happen: the half-2 setstate WRITES `_ktp_h2`, and that write is
    this test's positive control. Without it, asserting "empty" would pass on a
    server where the key was simply never set.
    """
    assert live_h2.setstate(half=2, allies=7, axis=5, h1_team1=3, h1_team2=2).accepted
    stale = live_h2.get_localinfo("_ktp_h2")
    assert stale, (
        "positive control failed: a half-2 setstate did not write _ktp_h2, so "
        "this test cannot prove the half-1 path clears it"
    )

    assert live_h2.setstate(half=1, allies=3, axis=2, h1_team1=3, h1_team2=2).accepted

    assert live_h2.get_localinfo("_ktp_h2") == "", (
        f"_ktp_h2 survived a half-1 setstate (was {stale!r}) — the next map "
        f"load would treat this live match as finished"
    )


# ---------------------------------------------------------------------------
# Refusals — input domain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "token",
    ["-5", "abc", "1000", "2.5", "1e3"],
    ids=["negative", "letters", "over_999", "decimal", "exponent"],
)
def test_setstate_rejects_non_domain_tokens(live_h2, token):
    """Scores must be digits only, 0..999. The domain matters as much as the
    arithmetic: `execute_setstate` passes these to `dodx_set_team_score()`,
    which bounds-checks the team index and writes the score verbatim — so a
    negative would produce a match state no production input can reach.

    `-5` is the case that mattered. Review caught the first cut of the test rcon
    using a bare `str_to_num`, where `setstate 1 -5 -3 -5 -3` satisfies the
    half-1 consistency rule (totals equal the H1 pair) and would have been
    accepted, writing negative scores. The chat path's tokenizer always
    rejected it; the test path skipped that rule.
    """
    result = live_h2.setstate(half=1, allies=token, axis=1, h1_team1=token, h1_team2=1)

    assert not result.accepted, f"token {token!r} was accepted"
    assert result.reason == "parse=bad_token", (
        f"token {token!r} refused for the wrong reason: {result.reason!r}"
    )


@pytest.mark.parametrize(
    "argstr",
    ["", "1", "1 2 3 4", "1 2 3 4 5 6"],
    ids=["none", "one", "four", "six"],
)
def test_setstate_requires_exactly_five_arguments(hlds, live_h2, argstr):
    """Wrong arity is a malformed call, not a refusal — the plugin answers
    `ERROR`, which the driver surfaces as MatchDriverError.

    Kept separate from the token tests because an empty or space-padded token
    changes the ARGUMENT COUNT rather than reaching the parser, so folding them
    together would assert the wrong mechanism. Arity is also what defends the
    `g_fakecmd` path, where `read_argv` serves only indices 0-2 and would
    silently yield empty strings for the rest.
    """
    out = hlds.rcon(f"amx_ktp_test_setstate {argstr}".rstrip())
    assert "KTP_TEST_SETSTATE: ERROR" in out, (
        f"arity {argstr!r} should be an ERROR, got: {out!r}"
    )

    # And the match must be untouched by a malformed call.
    state = live_h2.get_state()
    assert state.match_live, "a malformed setstate call disturbed the live match"


def test_setstate_accepts_domain_boundaries(live_h2):
    """Positive control for the test above: 0 and 999 are inside the domain and
    must be accepted. Without this, `test_setstate_rejects_non_domain_tokens`
    would still pass against a parser that rejected everything.
    """
    result = live_h2.setstate(half=1, allies=0, axis=999, h1_team1=0, h1_team2=999)

    assert result.accepted, (
        f"boundary values 0 and 999 were refused ({result.reason}) — the domain "
        f"check is too strict, and the rejection test above proves nothing"
    )


# ---------------------------------------------------------------------------
# Refusals — score arithmetic
# ---------------------------------------------------------------------------

def test_setstate_rejects_negative_second_half(live_h2):
    """Totals below the 1st-half scores describe an impossible match. H1 of 6
    with an Axis total of 2 would make team1's 2nd half -4."""
    result = live_h2.setstate(half=2, allies=9, axis=2, h1_team1=6, h1_team2=1)

    assert not result.accepted, "impossible score state was accepted"
    assert result.reason == "scores=negative_h2", (
        f"wrong refusal reason: {result.reason!r}"
    )


def test_setstate_half1_rejects_mismatched_totals(live_h2):
    """In half 1 the totals and the H1 pair must agree; anything else means the
    admin misread which number goes where."""
    result = live_h2.setstate(half=1, allies=5, axis=4, h1_team1=3, h1_team2=2)

    assert not result.accepted, "inconsistent half-1 numbers were accepted"
    assert result.reason == "scores=h1_mismatch", (
        f"wrong refusal reason: {result.reason!r}"
    )


@pytest.mark.parametrize("half", [0, 3, 99])
def test_setstate_rejects_invalid_half(live_h2, half):
    """Only halves 1 and 2 exist. Overtime is refused by a separate gate."""
    result = live_h2.setstate(half=half, allies=4, axis=4, h1_team1=4, h1_team2=4)

    assert not result.accepted, f"half={half} was accepted"
    assert result.reason == "scores=bad_half", (
        f"wrong refusal reason for half={half}: {result.reason!r}"
    )


def test_setstate_rejected_state_is_not_applied(live_h2):
    """A refusal must leave the match untouched. Without this, a rejected
    setstate that had already written some fields would leave the match in a
    state that is neither the old one nor the requested one — worse than either.
    """
    before = live_h2.get_state()

    result = live_h2.setstate(half=2, allies=9, axis=2, h1_team1=6, h1_team2=1)
    assert not result.accepted

    after = live_h2.get_state()
    assert (after.current_half, after.score_team1, after.score_team2) == (
        before.current_half, before.score_team1, before.score_team2
    ), (
        f"rejected setstate mutated match state: "
        f"{(before.current_half, before.score_team1, before.score_team2)} -> "
        f"{(after.current_half, after.score_team1, after.score_team2)}"
    )


# ---------------------------------------------------------------------------
# Refusals — state gates
# ---------------------------------------------------------------------------

def test_setstate_refused_when_no_live_match(hlds):
    """`.setstate` repairs a live match; with none running there is nothing to
    repair and the numbers would be adopted into an idle state machine."""
    driver = MatchDriver(hlds)
    driver.reset()

    result = driver.setstate(half=2, allies=8, axis=5, h1_team1=3, h1_team2=2)

    assert not result.accepted, "setstate was accepted with no live match"
    assert result.reason == "gate=not_live", (
        f"wrong refusal reason: {result.reason!r}"
    )


def test_setstate_refused_before_match_goes_live(hlds):
    """PENDING is not LIVE. Separate from the idle case above because it is the
    reachable operator mistake — typing `.setstate` during the ready-up phase
    after a bad `.ktp`, when the scoreboard already shows stale numbers."""
    driver = MatchDriver(hlds)
    driver.setup_match(MatchType.COMPETITIVE)
    driver.advance_pending()
    try:
        result = driver.setstate(half=1, allies=2, axis=2, h1_team1=2, h1_team2=2)
        assert not result.accepted, "setstate was accepted while merely PENDING"
        assert result.reason == "gate=not_live", (
            f"wrong refusal reason: {result.reason!r}"
        )
    finally:
        driver.reset()


# ---------------------------------------------------------------------------
# Out of reach from Tier 2 — stated so the gap is not mistaken for coverage
# ---------------------------------------------------------------------------
#
# `gate=overtime` and `gate=intermission` are NOT exercised here.
#
#   - `g_inOvertime` is set only by the localinfo OT-restoration path and the
#     regulation-tie OT transition. Neither is reachable from the test rcons,
#     and forcing the flag would need a new test-mode command that is itself
#     unverified — trading one untested path for another.
#   - `is_in_intermission()` is a real half/map-change window; the harness
#     drives half transitions through `end_first_half`, which does not enter it.
#
# Both refusals ARE covered indirectly: all three gates live in the single
# `setstate_gate_reason()` stock that `test_setstate_refused_when_no_live_match`
# proves the rcon consults. That bounds the risk to the two gate CONDITIONS, not
# to the gate mechanism. It is not equivalent to testing them, and should not be
# recorded as such.
