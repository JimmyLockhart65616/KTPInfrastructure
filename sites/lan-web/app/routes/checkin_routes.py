"""LAN-day check-in. Players self-check-in via Discord login; captains confirm
the team. Public board shows who's present.

Check-in runs in two passes — Friday's draft headcount, then a fresh Saturday
run for group play. Staff clear the board between them via checkin_reset
(NULLs checked_in_at on players + teams)."""
import csv
import io
from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from .. import auth, common, db
from ..templating import templates

router = APIRouter()


def _sheet_safe(name: str) -> str:
    """Clan tags lead with formula characters — =DoD=, -=SS=-, +Rep, @dolf — and
    Sheets/Excel evaluate them, so the name lands as #NAME? in the draft sheet.
    A leading apostrophe is the text marker; Sheets hides it, Excel shows it."""
    return "'" + name if name.startswith(("=", "+", "-", "@")) else name


def _draft_pool() -> list[str]:
    """Checked-in players as one flat alphabetical list — the Friday draft pool.

    Team-agnostic on purpose: Friday drafts players, so the roster they arrived
    on is noise here. Sorted on the real name, so the formula guard can't reorder
    anyone. Read in its own connection from the board's, so a check-in landing
    mid-render can leave this one name ahead — harmless at LAN scale."""
    rows = db.query_all("SELECT display_name FROM lan_players WHERE checked_in_at IS NOT NULL")
    names = sorted((n for n in ((r["display_name"] or "").strip() for r in rows) if n), key=str.casefold)
    return [_sheet_safe(n) for n in names]


@router.get("/checkin", name="checkin")
def checkin_page(request: Request):
    teams = db.query_all("SELECT id, name, tag, checked_in_at FROM lan_teams ORDER BY name")
    for t in teams:
        roster = db.query_all(
            "SELECT display_name, is_captain, checked_in_at FROM lan_players "
            "WHERE team_id=%s ORDER BY is_captain DESC, display_name",
            (t["id"],),
        )
        t["roster"] = roster
        t["checked_in"] = [p for p in roster if p["checked_in_at"]]
        t["present"] = len(t["checked_in"])
        t["total"] = len(roster)
    ctx = common.base_ctx(request, "checkin")
    ctx["teams"] = teams
    # Keeps the flat export list (and its query) out of the public page. The
    # board above is public by design, so this is tidiness, not confidentiality.
    ctx["draft_pool"] = _draft_pool() if ctx["is_admin"] else []
    return templates.TemplateResponse(request, "checkin.html", ctx)


@router.get("/admin/checkin.csv", name="checkin_export")
def checkin_export(request: Request):
    """Staff: the draft pool as a CSV, for when the clipboard isn't an option."""
    auth.require_admin(request)
    buf = io.StringIO()
    # Default CRLF terminator on purpose: it keeps CR in csv's quoting triggers,
    # so a name with an interior CR can't split into two rows.
    w = csv.writer(buf)
    w.writerow(["Player"])
    for name in _draft_pool():
        w.writerow([name])
    return Response(
        # BOM so Excel reads it as UTF-8 on a double-click; Sheets ignores it.
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition":
                f'attachment; filename="wsdod-checkin-{date.today().isoformat()}.csv"',
        },
    )


@router.post("/checkin/me", name="checkin_me")
def checkin_me(request: Request):
    ident = auth.require_login(request)
    db.execute("UPDATE lan_players SET checked_in_at=NOW() WHERE id=%s", (ident["player_id"],))
    return RedirectResponse(request.url_for("checkin"), status_code=303)


@router.post("/checkin/team", name="checkin_team")
def checkin_team(request: Request):
    ident = auth.require_captain(request)
    db.execute("UPDATE lan_teams SET checked_in_at=NOW() WHERE id=%s", (ident["team_id"],))
    db.execute(
        "UPDATE lan_players SET checked_in_at=NOW() WHERE id=%s AND checked_in_at IS NULL",
        (ident["player_id"],),
    )
    return RedirectResponse(request.url_for("checkin"), status_code=303)


@router.post("/admin/checkin/reset", name="checkin_reset")
def checkin_reset(request: Request):
    """Staff: clear the whole board so the next pass (Friday -> Saturday) starts fresh."""
    auth.require_admin(request)
    db.execute("UPDATE lan_players SET checked_in_at=NULL WHERE checked_in_at IS NOT NULL")
    db.execute("UPDATE lan_teams SET checked_in_at=NULL WHERE checked_in_at IS NOT NULL")
    return RedirectResponse(request.url_for("checkin"), status_code=303)
