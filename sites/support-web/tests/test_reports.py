"""Report intake tests.

The routing tests matter most: a cheating accusation reaching the general ops
room is the failure the two-channel design exists to prevent, and it is silent
when it happens.
"""

import json

import pytest

from app.reports import (
    MAX_BODY,
    Category,
    Channel,
    RateLimiter,
    Report,
    ReportRejected,
    embed_fields,
    validate,
)

LABELS = {"Atlanta 1", "Dallas 3", "Chicago 2"}


def ok(**kw):
    args = dict(category="lag", body="choke spikes every round", elapsed=10.0)
    args.update(kw)
    return validate(**args)


# --- routing -------------------------------------------------------------

@pytest.mark.parametrize("cat", ["player_conduct", "cheating"])
def test_accusations_route_to_the_narrow_channel(cat):
    assert ok(category=cat).channel is Channel.PLAYER


@pytest.mark.parametrize("cat", ["server_down", "lag", "crash", "config", "hltv_demo", "other"])
def test_everything_else_routes_to_ops(cat):
    assert ok(category=cat).channel is Channel.SERVER


def test_every_category_has_a_channel():
    # A category added later without a routing rule must not silently default
    # a cheating report into the ops room.
    for cat in Category:
        assert cat.channel in (Channel.SERVER, Channel.PLAYER)


def test_submitter_cannot_choose_the_destination():
    # There is no channel parameter on validate() at all -- routing is derived.
    with pytest.raises(TypeError):
        validate(category="lag", body="x", elapsed=10.0, channel="server")


# --- validation ----------------------------------------------------------

def test_honeypot_is_rejected_quietly():
    with pytest.raises(ReportRejected, match="dropped"):
        ok(honeypot="http://spam")


def test_instant_submission_is_rejected():
    with pytest.raises(ReportRejected):
        ok(elapsed=0.4)
    assert ok(elapsed=3.0).body


def test_unknown_category_and_empty_body_are_rejected():
    with pytest.raises(ReportRejected):
        ok(category="not_a_category")
    for empty in ("", "   ", "\n\t "):
        with pytest.raises(ReportRejected):
            ok(body=empty)


def test_oversize_body_and_handle_are_rejected():
    assert ok(body="x" * MAX_BODY).body
    with pytest.raises(ReportRejected):
        ok(body="x" * (MAX_BODY + 1))
    with pytest.raises(ReportRejected):
        ok(handle="h" * 65)


def test_server_label_must_come_from_the_known_list():
    assert ok(server_label="Dallas 3", valid_labels=LABELS).server_label == "Dallas 3"
    with pytest.raises(ReportRejected):
        ok(server_label="<script>alert(1)</script>", valid_labels=LABELS)
    # Not specifying a server stays legal -- plenty of reports are fleet-wide.
    assert ok(valid_labels=LABELS).server_label is None


def test_body_is_stripped_but_not_otherwise_rewritten():
    r = ok(body="  it **broke** <b>badly</b>  ")
    assert r.body == "it **broke** <b>badly</b>"


# --- rate limiting -------------------------------------------------------

def test_ip_is_hashed_and_salted_before_use():
    k = RateLimiter.key("203.0.113.9", "s3cret")
    assert "203.0.113.9" not in k and len(k) == 32
    assert k != RateLimiter.key("203.0.113.9", "other-salt")


def test_allows_the_limit_then_blocks():
    rl, k, t = RateLimiter(), "k", 1000.0
    assert [rl.check(k, t + i) for i in range(3)] == [True, True, True]
    assert rl.check(k, t + 4) is False
    assert rl.retry_after(k, t + 4) > 0


def test_window_expiry_lets_the_key_through_again():
    rl, k, t = RateLimiter(), "k", 1000.0
    for i in range(3):
        rl.check(k, t + i)
    assert rl.check(k, t + 3601) is True


def test_keys_do_not_interfere():
    rl, t = RateLimiter(), 1000.0
    for i in range(3):
        rl.check("a", t + i)
    assert rl.check("a", t + 4) is False
    assert rl.check("b", t + 4) is True


def test_prune_drops_expired_buckets():
    rl, t = RateLimiter(), 1000.0
    rl.check("old", t)
    rl.check("new", t + 3500)
    rl.prune(t + 3600)
    assert list(rl._hits) == ["new"]


# --- relay payload -------------------------------------------------------

def test_embed_suppresses_mentions_even_when_the_body_contains_one():
    r = Report(Category.CHEATING, "Dallas 3", "@everyone he is walling <@&123>", None)
    payload = embed_fields(r, "abc123")
    assert payload["allowed_mentions"] == {"parse": []}
    # The text is carried verbatim -- suppression is the relay's job, not
    # mangling the reporter's words.
    assert "@everyone" in json.dumps(payload)


def test_embed_truncates_to_discord_field_limit():
    r = Report(Category.LAG, None, "x" * 4000, None)
    assert len(embed_fields(r, "id")["fields"][2]["value"]) == 1024


def test_anonymous_reporter_is_labelled_not_blank():
    payload = embed_fields(Report(Category.LAG, None, "b", None), "id")
    assert payload["fields"][1]["value"] == "anonymous"


# --- relay endpoint construction -----------------------------------------

def test_relay_accepts_a_base_url_or_one_that_already_has_the_path():
    """/etc/ktp/discord-relay.conf stores RELAY_URL with /reply on the end; an
    env var is more naturally a base. Both must reach the same endpoint."""
    import httpx
    from app import relay

    seen = []

    def fake_post(url, **kw):
        seen.append(url)
        return httpx.Response(200, request=httpx.Request("POST", url))

    real, httpx.post = httpx.post, fake_post
    try:
        for given in ("https://r.example.com",
                      "https://r.example.com/",
                      "https://r.example.com/reply",
                      "https://r.example.com/reply/"):
            relay.post_embed(given, "secret", "123", {"title": "t"})
    finally:
        httpx.post = real

    assert seen == ["https://r.example.com/reply"] * 4


def test_relay_reports_failure_instead_of_raising():
    from app import relay
    r = relay.post_embed("", "s", "1", {})          # not configured
    assert r.ok is False and "not configured" in r.error
