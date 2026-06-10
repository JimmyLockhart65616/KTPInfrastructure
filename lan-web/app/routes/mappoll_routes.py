"""Captain map-skip poll + public results + admin controls.

Each captain casts one ballot naming the map to skip on Saturday; the most-voted
map is dropped from the Saturday rotation and used as the play-in map."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, mapskip
from ..templating import templates

router = APIRouter()


def _teams_by_id() -> dict[int, dict]:
    return {t["id"]: t for t in db.query_all("SELECT id, name, tag FROM lan_teams ORDER BY name")}


@router.get("/mappoll", name="mappoll")
def mappoll_form(request: Request):
    ident = auth.require_captain(request)
    teams = _teams_by_id()
    ctx = common.base_ctx(request, "mapskip")
    ctx.update(
        my_team=teams.get(ident["team_id"]),
        pool=mapskip.pool_maps(),
        current=mapskip.get_team_ballot(ident["team_id"]),
        poll_open=mapskip.poll_is_open(),
    )
    return templates.TemplateResponse(request, "mappoll.html", ctx)


@router.post("/mappoll")
async def mappoll_submit(request: Request):
    ident = auth.require_captain(request)
    if not mapskip.poll_is_open():
        raise HTTPException(403, "The map-skip poll is closed.")
    form = await request.form()
    skip_map = (form.get("skip_map") or "").strip()
    if skip_map not in mapskip.pool_maps():
        raise HTTPException(400, "Pick one map from the pool.")
    mapskip.save_ballot(ident["team_id"], skip_map, submitted_by=ident["discord_id"])
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)


@router.get("/mapskip", name="mapskip")
def mapskip_page(request: Request):
    teams = _teams_by_id()
    ballots = mapskip.get_all_ballots()
    ordered, counts = mapskip.tally(ballots, mapskip.pool_maps())
    ctx = common.base_ctx(request, "mapskip")
    ctx.update(
        teams=teams,
        ballots=ballots,
        submitted=sorted(ballots.keys()),
        ordered=ordered,
        counts=counts,
        total=sum(counts.values()),
        poll_open=mapskip.poll_is_open(),
        locked=mapskip.locked_skip_map(),
        is_admin=auth.is_admin(request),
    )
    return templates.TemplateResponse(request, "mapskip.html", ctx)


# ── admin controls (staff only) ──────────────────────────────────────────
@router.post("/admin/mappoll/open")
def mappoll_open(request: Request):
    auth.require_admin(request)
    mapskip.set_setting("map_skip_poll_open", "1")
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)


@router.post("/admin/mappoll/close")
def mappoll_close(request: Request):
    auth.require_admin(request)
    mapskip.set_setting("map_skip_poll_open", "0")
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)


@router.post("/admin/mappoll/compute")
def mappoll_compute(request: Request):
    auth.require_admin(request)
    mapskip.compute_and_store()
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)
