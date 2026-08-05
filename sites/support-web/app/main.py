"""support.ktpdod.com — one page, rendered per session by tier.

Route surface is small on purpose. Everything with real logic lives in a pure
module (tiers, status, reports, tickets, season) and is tested without a
request; this file is wiring.
"""

from __future__ import annotations

import logging
import secrets

from authlib.integrations.starlette_client import OAuth
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import relay, status as st, store
from .config import settings
from .reports import RateLimiter, ReportRejected, validate
from .tiers import Tier, can_view_detail_status, resolve, visible_sections

log = logging.getLogger("support-web")

app = FastAPI(title="KTP Support", docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret, https_only=True)
templates = Jinja2Templates(directory="app/templates")

limiter = RateLimiter()

oauth = OAuth()
oauth.register(
    name="discord",
    client_id=settings.discord_client_id,
    client_secret=settings.discord_client_secret,
    access_token_url="https://discord.com/api/oauth2/token",
    authorize_url="https://discord.com/api/oauth2/authorize",
    api_base_url="https://discord.com/api/",
    # `identify` only. Guild-role gating would need guilds.members.read plus a
    # bot token on an internet-facing app; see design/DESIGN.md.
    client_kwargs={"scope": "identify", "token_endpoint_auth_method": "client_secret_post"},
)

SESSION_ID, SESSION_NAME = "discord_id", "discord_name"


def current_tier(request: Request) -> Tier:
    return resolve(
        request.session.get(SESSION_ID), settings.ktp_admin_ids, settings.one3_admin_ids
    )


def client_ip(request: Request) -> str:
    """Left-most X-Forwarded-For entry, since nginx sits in front.

    Trusted because only our own proxy can reach the app port; if this is ever
    exposed directly, this becomes attacker-controlled and the rate limiter
    stops working.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "0.0.0.0")


@app.get("/", response_class=HTMLResponse)
def index(request: Request, tier: Tier = Depends(current_tier)):
    doc = st.load(settings.public_json)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tier": tier.value,
            "sections": visible_sections(tier),
            "status": st.view(doc),
            "server_labels": sorted(st.server_labels(doc)),
            "user": request.session.get(SESSION_NAME),
        },
    )


@app.get("/healthz")
def healthz():
    """Liveness only -- deliberately says nothing about the fleet."""
    return {"ok": True}


@app.get("/api/status")
def api_status():
    """Same document the page renders, with the same staleness verdict applied.

    Serving it here rather than letting callers read public.json directly means
    a stale document is reported as stale to them too.
    """
    return JSONResponse(st.view(st.load(settings.public_json)))


@app.get("/api/status/detail")
def api_status_detail(tier: Tier = Depends(current_tier)):
    if not can_view_detail_status(tier):
        return JSONResponse({"detail": "not found"}, status_code=404)
    return JSONResponse(st.load(settings.detail_json) or {})


@app.post("/api/report")
async def api_report(
    request: Request,
    category: str = Form(...),
    body: str = Form(...),
    server_label: str = Form(""),
    handle: str = Form(""),
    website: str = Form(""),          # honeypot; real users never see it
    started: str = Form("0"),
):
    key = RateLimiter.key(client_ip(request), settings.report_salt)
    if not limiter.check(key):
        return JSONResponse(
            {"ok": False, "error": "Too many reports from here. Try again later."},
            status_code=429,
            headers={"Retry-After": str(limiter.retry_after(key))},
        )

    labels = st.server_labels(st.load(settings.public_json))
    try:
        elapsed = max(0.0, float(started or 0))
    except ValueError:
        elapsed = 0.0

    try:
        report = validate(
            category=category,
            body=body,
            server_label=server_label,
            handle=handle,
            honeypot=website,
            elapsed=elapsed,
            valid_labels=labels or None,
        )
    except ReportRejected as exc:
        # The honeypot path returns 200: a bot must not learn it was caught.
        if str(exc) == "dropped":
            return JSONResponse({"ok": True})
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    intake_id = secrets.token_hex(6)
    deliver_report(report, intake_id, key)
    # The reporter is told "sent" either way. Delivery is our problem from here:
    # the row is durable and the unrelayed index is the retry queue, so telling
    # them it failed would make them re-submit something we already have.
    return JSONResponse({"ok": True, "intake": intake_id})


def deliver_report(report, intake_id: str, ip_hash: str) -> None:
    """Persist, then relay, then mark. Never raises into the request."""
    conn = report_id = None
    try:
        conn = store.connect(**settings.db_kwargs)
        report_id = store.insert_report(conn, intake_id, report, ip_hash)
    except Exception as exc:                     # noqa: BLE001 - log and continue
        log.error("report %s could not be stored: %s", intake_id, exc)

    result = relay.post_embed(
        settings.relay_url,
        settings.relay_secret,
        settings.channel_for(report.channel.value),
        relay.report_embed(report, intake_id),
    )
    if not result.ok:
        log.error("report %s relay failed (%s): %s", intake_id, result.status, result.error)
    elif conn and report_id:
        try:
            store.mark_relayed(conn, report_id)
        except Exception as exc:                 # noqa: BLE001
            # Worst case it is retried and posts twice, which is recoverable;
            # a lost report is not.
            log.error("report %s relayed but not marked: %s", intake_id, exc)
    if conn:
        conn.close()


@app.get("/auth/login")
async def auth_login(request: Request):
    if not settings.oauth_configured:
        return RedirectResponse("/", status_code=303)
    return await oauth.discord.authorize_redirect(request, settings.discord_redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.discord.authorize_access_token(request)
    me = (await oauth.discord.get("users/@me", token=token)).json()
    request.session[SESSION_ID] = str(me.get("id", ""))
    request.session[SESSION_NAME] = me.get("global_name") or me.get("username")
    return RedirectResponse("/", status_code=303)


@app.get("/auth/logout")
def auth_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
