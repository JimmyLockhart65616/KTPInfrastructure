"""Poller tests.

The disclosure test is the important one here: `public.json` is served to anyone
on the internet, so a field leaking into it is a real exposure, not a cosmetic
bug. It asserts on the serialised bytes rather than on dict keys, because a
nested value would pass a key check and still ship the address.
"""

import json

import pytest

from app import poller as P
from app.a2s import ServerInfo
from app.hostname import parse


def _ok(label, region, hostname, players=8, mx=13, bots=0, ip="10.9.8.7", port=27015):
    info = ServerInfo(hostname, "dod_donner", players, mx, bots)
    return {
        "instance": P.Instance(region, label, ip, port),
        "up": True, "degraded": False, "misses": 0,
        "info": info, "name": parse(hostname), "last_ok": 1000.0,
    }


def _down(label, region, misses=P.DOWN_AFTER, ip="10.9.8.7", port=27016):
    return {
        "instance": P.Instance(region, label, ip, port),
        "up": misses < P.DOWN_AFTER, "degraded": True, "misses": misses,
        "error": "timeout", "last_ok": 500.0,
    }


def test_fleet_is_24_instances_on_the_expected_ports():
    f = P.fleet()
    assert len(f) == 24
    assert sum(1 for i in f if i.region == "Chicago") == 4
    assert {i.port for i in f} <= {27015, 27016, 27017, 27018, 27019}
    assert max(i.port for i in f if i.region == "Chicago") == 27018


def test_public_document_never_leaks_topology():
    results = [
        _ok("Atlanta 1", "Atlanta", "KTP - Atlanta 1 - 12MAN - LIVE - 2ND HALF",
            ip="74.91.121.9", port=27015),
        _down("Dallas 2", "Dallas", ip="74.91.126.55", port=27016),
    ]
    blob = json.dumps(P.public_document(results))
    for secret in ("74.91.121.9", "74.91.126.55", "27015", "27016", "timeout",
                   "misses", "last_ok", "address"):
        assert secret not in blob, f"public.json leaked {secret!r}"


def test_public_document_carries_map_players_and_match_state():
    doc = P.public_document(
        [_ok("Atlanta 1", "Atlanta", "KTP - Atlanta 1 - 12MAN - LIVE - 2ND HALF", players=9)]
    )
    s = doc["servers"][0]
    assert s == {"region": "Atlanta", "label": "Atlanta 1", "up": True,
                 "map": "dod_donner", "players": 9, "max_players": 13,
                 "match_type": "12MAN", "state": "LIVE - 2ND HALF"}


def test_idle_server_reports_no_match_fields():
    s = P.public_document([_ok("Denver 3", "Denver", "KTP - Denver 3")])["servers"][0]
    assert "match_type" not in s and "state" not in s
    assert s["map"] == "dod_donner"


def test_down_server_exposes_only_the_fact_that_it_is_down():
    s = P.public_document([_down("Dallas 2", "Dallas")])["servers"][0]
    assert s == {"region": "Dallas", "label": "Dallas 2", "up": False}


def test_summary_counts_humans_not_slots():
    results = [_ok("A 1", "Atlanta", "KTP - Atlanta 1", players=5, bots=2),
               _ok("A 2", "Atlanta", "KTP - Atlanta 2", players=3, bots=0),
               _down("A 3", "Atlanta")]
    doc = P.public_document(results)
    assert doc["summary"] == {"up": 2, "total": 3, "players": 6}


def test_one_miss_is_not_down():
    assert P.public_document([_down("A 1", "Atlanta", misses=1)])["servers"][0]["up"] is True
    assert P.public_document([_down("A 1", "Atlanta", misses=2)])["servers"][0]["up"] is True
    assert P.public_document([_down("A 1", "Atlanta", misses=3)])["servers"][0]["up"] is False


def test_documents_are_timestamped_so_staleness_is_detectable():
    assert P.public_document([], now=1234)["generated"] == 1234
    assert P.detail_document([], now=1234)["generated"] == 1234


def test_detail_document_keeps_what_public_drops():
    blob = json.dumps(P.detail_document([_down("Dallas 2", "Dallas", ip="74.91.126.55")]))
    assert "74.91.126.55:27016" in blob and "timeout" in blob


def test_write_atomic_leaves_no_partial_file(tmp_path):
    target = tmp_path / "public.json"
    P.write_atomic(str(target), {"generated": 1, "servers": []})
    assert json.loads(target.read_text())["generated"] == 1
    P.write_atomic(str(target), {"generated": 2, "servers": []})
    assert json.loads(target.read_text())["generated"] == 2
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_atomic_does_not_clobber_on_serialise_failure(tmp_path):
    target = tmp_path / "public.json"
    P.write_atomic(str(target), {"generated": 1})
    with pytest.raises(TypeError):
        P.write_atomic(str(target), {"bad": object()})
    assert json.loads(target.read_text())["generated"] == 1   # previous doc intact
    assert list(tmp_path.glob("*.tmp")) == []


def test_roster_count_wins_over_the_a2s_slot_count():
    # A2S says 1 (the HLTV proxy); the roster says 0 humans. The page must not
    # advertise a player on an empty server -- measured on production 2026-08-05.
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=1, bots=0)
    r["humans"] = 0
    assert P.public_document([r])["servers"][0]["players"] == 0


def test_falls_back_to_slot_count_when_the_roster_query_fails():
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=5, bots=0)
    r["humans"] = None
    assert P.public_document([r])["servers"][0]["players"] == 5


def test_summary_players_uses_the_roster_too():
    rs = []
    for i, humans in enumerate((0, 9, 0)):
        r = _ok(f"A {i}", "Atlanta", f"KTP - Atlanta {i}", players=humans + 1)
        r["humans"] = humans
        rs.append(r)
    assert P.public_document(rs)["summary"]["players"] == 9
