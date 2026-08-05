"""Hostname parse tests.

Every base name here contains " - ", because that is the whole hazard: the real
fleet is named "KTP - Atlanta 1", so a left-to-right split mangles all 24.
"""

import pytest

from app.hostname import parse

LIVE_BASES = ["KTP - Atlanta 1", "KTP - Dallas 5", "KTP - Chicago 1", "KTP - New York 3"]


@pytest.mark.parametrize("base", LIVE_BASES)
def test_idle_server_is_returned_untouched(base):
    got = parse(base)
    assert got.base == base
    assert (got.match_type, got.state) == (None, None)
    assert not got.in_match and not got.is_live


@pytest.mark.parametrize(
    "suffix,mtype,state",
    [
        ("KTP - LIVE - 1ST HALF", "KTP", "LIVE - 1ST HALF"),
        ("KTP - LIVE - 2ND HALF", "KTP", "LIVE - 2ND HALF"),
        ("12MAN - LIVE - 2ND HALF", "12MAN", "LIVE - 2ND HALF"),
        ("SCRIM - PENDING", "SCRIM", "PENDING"),
        ("DRAFT - PAUSED", "DRAFT", "PAUSED"),
        ("MATCH - LIVE", "MATCH", "LIVE"),
        ("KTP OT - LIVE - OT1", "KTP OT", "LIVE - OT1"),
        ("DRAFT OT - LIVE - OT2", "DRAFT OT", "LIVE - OT2"),
        ("KTP OT - PAUSED", "KTP OT", "PAUSED"),
    ],
)
def test_base_survives_every_type_and_state(suffix, mtype, state):
    base = "KTP - Atlanta 1"
    got = parse(f"{base} - {suffix}")
    assert got.base == base, "base was mangled -- left-to-right split regression"
    assert (got.match_type, got.state) == (mtype, state)


def test_longest_token_wins():
    # "KTP OT" must not be parsed as "KTP", nor "LIVE - 1ST HALF" as "LIVE".
    assert parse("KTP - Denver 2 - KTP OT - LIVE - OT3").match_type == "KTP OT"
    assert parse("KTP - Denver 2 - KTP - LIVE - 1ST HALF").state == "LIVE - 1ST HALF"


def test_double_digit_overtime_rounds():
    assert parse("KTP - Dallas 1 - KTP OT - LIVE - OT12").state == "LIVE - OT12"


def test_is_live_only_for_live_states():
    assert parse("KTP - Dallas 1 - KTP - LIVE").is_live
    assert parse("KTP - Dallas 1 - KTP - LIVE - OT1").is_live
    assert not parse("KTP - Dallas 1 - KTP - PAUSED").is_live
    assert not parse("KTP - Dallas 1 - SCRIM - PENDING").is_live


@pytest.mark.parametrize(
    "odd",
    [
        "",
        "   ",
        "Some Other Server",
        "KTP - Atlanta 1 - SOMETHING - ELSE",   # unknown tokens
        "KTP - Atlanta 1 - LIVE",               # state with no type in front
        "KTP - Atlanta 1 - KTP",                # type with no state after
        " - LIVE - 1ST HALF",                   # state but empty base
    ],
)
def test_unrecognised_shapes_never_raise_and_never_half_parse(odd):
    got = parse(odd)
    assert (got.match_type, got.state) == (None, None)
    assert got.base == odd.strip()


def test_a_base_that_itself_looks_like_a_state_is_still_safe():
    # Pathological but cheap to guarantee: state tokens inside the base.
    got = parse("KTP - LIVE Server - KTP - PAUSED")
    assert got.base == "KTP - LIVE Server"
    assert (got.match_type, got.state) == ("KTP", "PAUSED")
