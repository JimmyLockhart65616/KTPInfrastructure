"""A2S parse tests.

REAL_DALLAS / REAL_CHICAGO are verbatim captures taken from the live fleet on
2026-08-05 via the data server. A hand-built fixture would only prove the parser
agrees with my idea of the format; these prove it agrees with the servers.
"""

import pytest

from app.a2s import A2SError, ServerInfo, parse_info

REAL_DALLAS = (
    b"\xff\xff\xff\xffI0KTP - Dallas 1\x00dod_railroad2_s9a\x00dod\x00"
    b"Day of Defeat\x00\x1e\x00\x01\r\x00dl\x01\x011.1.2.6/Stdio\x00"
)
REAL_CHICAGO = (
    b"\xff\xff\xff\xffI0KTP - Chicago 1\x00dod_railroad2_s9a\x00dod\x00"
    b"Day of Defeat\x00\x1e\x00\x01\r\x00dl\x01\x011.1.2.6/Stdio"
)


def test_parses_a_real_reply():
    info = parse_info(REAL_DALLAS)
    assert info.hostname == "KTP - Dallas 1"
    assert info.map == "dod_railroad2_s9a"
    assert (info.players, info.max_players, info.bots) == (1, 13, 0)


def test_parses_a_reply_with_no_trailing_null():
    # Chicago's capture ends without the final terminator; the fields we read
    # all precede the version string, so this must still parse.
    assert parse_info(REAL_CHICAGO).hostname == "KTP - Chicago 1"


def test_humans_discounts_bots():
    assert ServerInfo("x", "y", 8, 16, 2).humans == 6
    assert ServerInfo("x", "y", 0, 16, 0).humans == 0
    assert ServerInfo("x", "y", 1, 16, 3).humans == 0   # never negative


@pytest.mark.parametrize(
    "bad",
    [
        b"",
        b"\xff\xff\xff\xff",
        b"\x01\x02\x03\x04I0name\x00",                       # bad magic
        b"\xff\xff\xff\xffm0legacy\x00",                     # unsupported type
        b"\xff\xff\xff\xffI0unterminated",                   # no null
        b"\xff\xff\xff\xffI0n\x00m\x00f\x00g\x00\x1e",       # truncated mid-struct
    ],
)
def test_malformed_replies_raise_a2serror_not_something_else(bad):
    # The poller catches A2SError to mark a host down; any other exception type
    # would escape and kill the whole poll run, taking all 24 with it.
    with pytest.raises(A2SError):
        parse_info(bad)
