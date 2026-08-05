"""Route tests.

These exist because the gating claims are only worth anything end to end: the
disclosure test reads the actual rendered HTML a logged-out visitor receives,
not the section list that produced it.
"""

import importlib
import json

import pytest
from fastapi.testclient import TestClient


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
