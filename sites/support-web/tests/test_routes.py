"""Route tests.

These exist because the gating claims are only worth anything end to end: the
disclosure test reads the actual rendered HTML a logged-out visitor receives,
not the section list that produced it.
"""

import importlib
import json

import pytest
from fastapi.testclient import TestClient


class _FakeConn:
    """Stands in for a pymysql connection; records that it was closed."""

    def __init__(self, log):
        self.log = log

    def close(self):
        self.log.append(("closed",))


@pytest.fixture
def client(tmp_path, monkeypatch):
    pub = tmp_path / "public.json"
    pub.write_text(json.dumps({
        "generated": 2_000_000_000,
        "servers": [{"region": "Dallas", "label": "Dallas 1", "up": True,
                     "map": "dod_donner", "players": 0, "max_players": 12, "hltv": True}],
        "summary": {"up": 1, "total": 1, "players": 0},
    }))
    det = tmp_path / "detail.json"
    det.write_text(json.dumps({"servers": [{"address": "74.91.126.55:27015"}]}))

    monkeypatch.setenv("SUPPORT_SESSION_SECRET", "test-secret")
    monkeypatch.setenv("SUPPORT_REPORT_SALT", "test-salt")
    monkeypatch.setenv("SUPPORT_PUBLIC_JSON", str(pub))
    monkeypatch.setenv("SUPPORT_DETAIL_JSON", str(det))
    monkeypatch.setenv("SUPPORT_KTP_ADMIN_IDS", "111")
    monkeypatch.setenv("SUPPORT_ONE3_ADMIN_IDS", "333")

    import app.config
    importlib.reload(app.config)
    import app.main
    m = importlib.reload(app.main)

    # No real MySQL and no real relay in tests. Without this the report tests
    # spend ~20s waiting on connection timeouts and, worse, would post to a live
    # Discord channel the moment someone ran them with a configured env.
    sent = []
    monkeypatch.setattr(m.store, "connect", lambda **kw: _FakeConn(sent))
    monkeypatch.setattr(m.store, "insert_report",
                        lambda conn, iid, rep, ip: sent.append(("row", iid, rep.channel.value)) or 1)
    monkeypatch.setattr(m.store, "mark_relayed",
                        lambda conn, rid: sent.append(("marked", rid)))
    monkeypatch.setattr(m.store, "insert_ticket",
                        lambda *a, **k: sent.append(("ticket",)) or 7)
    monkeypatch.setattr(m.store, "set_ticket_status", lambda *a, **k: True)
    monkeypatch.setattr(m.relay, "post_embed",
                        lambda url, sec, ch, emb, **kw: sent.append(("relay", ch, emb))
                        or m.relay.RelayResult(True, 200))
    m.delivered = sent

    def as_tier(did=None):
        from app.tiers import resolve
        m.app.dependency_overrides[m.current_tier] = lambda: resolve(
            did, {"111"}, {"333"}
        )
        return TestClient(m.app)

    yield as_tier
    m.app.dependency_overrides.clear()


# --- what a logged-out visitor actually receives --------------------------

def test_public_html_contains_no_admin_markup(client):
    html = client().get("/").text
    for gated in ("request_one3", "request_ktp", "commands", "ticket queue"):
        assert gated not in html, f"logged-out HTML leaked {gated!r}"
    assert "report-a-problem" in html and "Sponsor KTP" in html


def test_one3_sees_its_form_and_not_the_ktp_one(client):
    html = client("333").get("/").text
    assert "1.3 moderator request" in html
    assert "KTP privilege request" not in html and "ticket queue" not in html


def test_ktp_sees_everything(client):
    html = client("111").get("/").text
    for section in ("KTP privilege request", "bot command hub", "ticket queue"):
        assert section in html


def test_status_renders_capacity_with_the_proxy_flag(client):
    assert "0/12 +H" in client().get("/").text


# --- detail.json is gated -------------------------------------------------

@pytest.mark.parametrize("who", [None, "333"])
def test_detail_is_404_not_403_for_non_ktp(client, who):
    # 403 would confirm the endpoint exists; 404 says nothing.
    r = client(who).get("/api/status/detail")
    assert r.status_code == 404
    assert "74.91.126.55" not in r.text


def test_detail_reaches_ktp_admins(client):
    r = client("111").get("/api/status/detail")
    assert r.status_code == 200 and "74.91.126.55:27015" in r.text


def test_public_status_api_never_carries_addresses(client):
    assert "74.91.126.55" not in client().get("/api/status").text


def test_healthz_says_nothing_about_the_fleet(client):
    body = client().get("/healthz").json()
    assert body == {"ok": True}


# --- report intake --------------------------------------------------------

def form(**kw):
    d = {"category": "lag", "body": "choke spikes every round", "started": "12"}
    d.update(kw)
    return d


def test_a_valid_report_is_accepted(client):
    r = client().post("/api/report", data=form())
    assert r.status_code == 200 and r.json()["ok"] is True
    assert len(r.json()["intake"]) == 12


def test_honeypot_looks_identical_to_success(client):
    r = client().post("/api/report", data=form(website="http://spam"))
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert "intake" not in r.json()      # nothing was actually filed


def test_bad_category_and_empty_body_are_400(client):
    c = client()
    assert c.post("/api/report", data=form(category="nope")).status_code == 400
    assert c.post("/api/report", data=form(body="   ")).status_code == 400


def test_unknown_server_label_is_rejected(client):
    r = client().post("/api/report", data=form(server_label="<script>x</script>"))
    assert r.status_code == 400


def test_known_server_label_is_accepted(client):
    assert client().post("/api/report", data=form(server_label="Dallas 1")).status_code == 200


def test_rate_limit_kicks_in_and_reports_retry_after(client):
    c = client()
    codes = [c.post("/api/report", data=form()).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429
    assert int(c.post("/api/report", data=form()).headers["Retry-After"]) > 0


def test_instant_submission_is_rejected(client):
    assert client().post("/api/report", data=form(started="0.2")).status_code == 400


# --- delivery ordering ----------------------------------------------------

def test_report_is_stored_before_it_is_relayed_then_marked(client):
    import app.main as m
    c = client()
    assert c.post("/api/report", data=form()).status_code == 200
    kinds = [e[0] for e in m.delivered]
    assert kinds == ["row", "relay", "marked", "closed"], kinds


def test_cheating_report_relays_to_the_player_channel(client, monkeypatch):
    import app.main as m
    monkeypatch.setenv("SUPPORT_CHANNEL_PLAYER_REPORTS", "200")
    c = client()
    c.post("/api/report", data=form(category="cheating"))
    row = next(e for e in m.delivered if e[0] == "row")
    assert row[2] == "player"


def test_a_relay_failure_still_tells_the_reporter_it_was_sent(client, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m.store, "insert_ticket",
                        lambda *a, **k: sent.append(("ticket",)) or 7)
    monkeypatch.setattr(m.store, "set_ticket_status", lambda *a, **k: True)
    monkeypatch.setattr(m.relay, "post_embed",
                        lambda *a, **k: m.relay.RelayResult(False, 502, "bad gateway"))
    r = client().post("/api/report", data=form())
    # The row is durable and the unrelayed index is the retry queue; telling
    # them it failed would make them re-submit something we already have.
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "marked" not in [e[0] for e in m.delivered]


def test_a_database_failure_does_not_block_the_relay(client, monkeypatch):
    import app.main as m

    def boom(**kw):
        raise RuntimeError("mysql is down")

    monkeypatch.setattr(m.store, "connect", boom)
    r = client().post("/api/report", data=form())
    assert r.status_code == 200
    assert "relay" in [e[0] for e in m.delivered]   # report still reached Discord


# --- tickets --------------------------------------------------------------

def ticket_form(**kw):
    d = {"scope": "one3_moderator", "steam_id": "STEAM_0:1:12345", "display_name": "someone"}
    d.update(kw)
    return d


def test_public_cannot_see_or_file_tickets(client):
    r = client().post("/api/tickets", data=ticket_form())
    assert r.status_code == 404          # 404, not 403 -- says nothing


def test_one3_admin_may_request_only_its_own_scope(client):
    c = client("333")
    assert c.post("/api/tickets", data=ticket_form()).status_code == 200
    # The KTP form is never rendered for them, but the endpoint is still open.
    r = c.post("/api/tickets", data=ticket_form(scope="ktp_admin"))
    assert r.status_code == 403


def test_ktp_admin_may_request_any_scope(client):
    c = client("111")
    for scope in ("one3_moderator", "ktp_admin", "season_captain"):
        assert c.post("/api/tickets", data=ticket_form(scope=scope)).status_code == 200


@pytest.mark.parametrize("bad", ["", "76561198000000000", "STEAM_0:2:1", "STEAM_0:1:", "nonsense"])
def test_malformed_steamids_are_rejected(client, bad):
    r = client("111").post("/api/tickets", data=ticket_form(steam_id=bad))
    assert r.status_code == 400


def test_steamid_universe_digit_is_normalised(client):
    # STEAM_0:1:5 and STEAM_1:1:5 are the same account; storing both would
    # create two rows for one person and hide an existing grant.
    import app.main as m
    assert m.normalise_steamid("STEAM_1:1:5") == "STEAM_0:1:5"
    assert m.normalise_steamid("steam_0:1:5") == "STEAM_0:1:5"
    assert m.normalise_steamid("  STEAM_0:1:5  ") == "STEAM_0:1:5"


def test_only_ktp_admins_may_advance_a_ticket(client):
    data = {"current": "submitted", "target": "approved"}
    assert client().post("/api/tickets/1/status", data=data).status_code == 404
    assert client("333").post("/api/tickets/1/status", data=data).status_code == 404


def test_a_ticket_cannot_skip_approval(client):
    r = client("111").post("/api/tickets/1/status",
                           data={"current": "submitted", "target": "applied"})
    assert r.status_code == 409
    assert "not allowed" in r.json()["error"]


def test_a_lost_race_reports_conflict_rather_than_success(client, monkeypatch):
    import app.main as m
    monkeypatch.setattr(m.store, "set_ticket_status", lambda *a, **k: False)
    r = client("111").post("/api/tickets/1/status",
                           data={"current": "submitted", "target": "approved"})
    assert r.status_code == 409 and "already moved" in r.json()["error"]


def test_missing_display_name_gets_our_message_not_a_schema_error(client):
    r = client("111").post("/api/tickets", data=ticket_form(display_name="  "))
    assert r.status_code == 400 and r.json()["error"] == "Who is it for?"
