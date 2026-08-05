"""Tier gating and status freshness.

Both encode a refusal: never render admin markup to a logged-out visitor, and
never present stale data as live.
"""

import json

import pytest

from app import status as St
from app.tiers import Tier, can_view_detail_status, resolve, visible_sections

KTP = {"111", "222"}
ONE3 = {"333", "222"}          # 222 is deliberately in both


# --- tiers ---------------------------------------------------------------

@pytest.mark.parametrize("did", [None, "", "999", "0"])
def test_unknown_or_absent_accounts_are_public(did):
    assert resolve(did, KTP, ONE3) is Tier.PUBLIC


def test_membership_maps_to_tier():
    assert resolve("111", KTP, ONE3) is Tier.KTP
    assert resolve("333", KTP, ONE3) is Tier.ONE3


def test_ktp_wins_when_an_account_is_in_both_lists():
    assert resolve("222", KTP, ONE3) is Tier.KTP


def test_empty_allowlists_grant_nothing():
    assert resolve("111", set(), set()) is Tier.PUBLIC


def test_public_never_sees_admin_sections():
    sections = visible_sections(Tier.PUBLIC)
    assert sections == ["status", "report", "hub", "sponsor"]
    for gated in ("request_one3", "request_ktp", "commands", "console", "tickets"):
        assert gated not in sections


def test_one3_gets_its_own_request_form_and_nothing_ktp():
    sections = visible_sections(Tier.ONE3)
    assert "request_one3" in sections
    for ktp_only in ("request_ktp", "commands", "console", "tickets"):
        assert ktp_only not in sections


def test_ktp_gets_everything():
    sections = visible_sections(Tier.KTP)
    assert {"request_ktp", "commands", "console", "tickets"} <= set(sections)


def test_only_ktp_may_read_detail_status():
    assert can_view_detail_status(Tier.KTP)
    assert not can_view_detail_status(Tier.ONE3)
    assert not can_view_detail_status(Tier.PUBLIC)


def test_is_admin_excludes_public_only():
    assert not Tier.PUBLIC.is_admin
    assert Tier.ONE3.is_admin and Tier.KTP.is_admin


# --- freshness -----------------------------------------------------------

def doc(generated, servers=None):
    return {"generated": generated,
            "servers": servers if servers is not None else [{"label": "Atlanta 1", "up": True}],
            "summary": {"up": 1, "total": 1, "players": 0}}


def test_a_recent_document_is_fresh():
    assert St.freshness(doc(1000), now=1000 + St.STALE_AFTER) is St.Freshness.FRESH


def test_an_old_document_is_stale_not_healthy():
    assert St.freshness(doc(1000), now=1000 + St.STALE_AFTER + 1) is St.Freshness.STALE


@pytest.mark.parametrize("bad", [None, {}, {"servers": []}])
def test_absent_or_unstamped_documents_are_missing(bad):
    assert St.freshness(bad) is St.Freshness.MISSING


def test_stale_view_drops_the_server_list_entirely():
    # A greyed-out list still reads as a list and someone will trust the counts.
    v = St.view(doc(1000), now=1000 + 10_000)
    assert v["servers"] == [] and v["summary"] is None and v["message"]
    assert v["generated"] == 1000          # still say when it was last true


def test_fresh_view_passes_the_payload_through():
    v = St.view(doc(1000), now=1000)
    assert v["freshness"] == "fresh" and v["message"] is None
    assert v["summary"]["total"] == 1


def test_view_never_raises_on_a_missing_document():
    v = St.view(None)
    assert v["freshness"] == "missing" and v["servers"] == []


def test_load_tolerates_corrupt_and_absent_files(tmp_path):
    assert St.load(str(tmp_path / "nope.json")) is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert St.load(str(bad)) is None
    wrong = tmp_path / "wrong.json"
    wrong.write_text("[1,2,3]")            # valid JSON, wrong shape
    assert St.load(str(wrong)) is None
    good = tmp_path / "good.json"
    good.write_text(json.dumps(doc(5)))
    assert St.load(str(good))["generated"] == 5


def test_server_labels_feed_the_report_form_allowlist():
    assert St.server_labels(doc(1, [{"label": "Dallas 3"}, {"up": False}])) == {"Dallas 3"}
    assert St.server_labels(None) == set()
