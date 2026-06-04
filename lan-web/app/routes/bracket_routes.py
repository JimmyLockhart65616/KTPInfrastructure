"""Sunday bracket: auto-fed view, BO3 series reporting, admin generate."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, bracket, common, db, notify, seeding
from .. import schedule as sched
from ..templating import templates

router = APIRouter()


def _champ(row):
    if not row or row["status"] != "final" or not row["winner_team_id"]:
        return None
    return row["a_name"] if row["winner_team_id"] == row["team_a_id"] else row["b_name"]


@router.get("/bracket", name="bracket")
def bracket_page(request: Request):
    ctx = common.base_ctx(request, "bracket")
    db_rows = {r["mkey"]: r for r in bracket.get_bracket()}
    # Always draw the full shape from the BRACKET constant; overlay DB data where present.
    slots = []
    for m in bracket.BRACKET:
        r = db_rows.get(m["key"], {})
        slots.append({
            "mkey": m["key"], "label": m["label"], "bracket": m["bracket"], "stage": m["stage"],
            "source_a": m["a"], "source_b": m["b"],
            "a_name": r.get("a_name"), "b_name": r.get("b_name"),
            "team_a_id": r.get("team_a_id"), "team_b_id": r.get("team_b_id"),
            "score_a": r.get("score_a"), "score_b": r.get("score_b"),
            "winner_team_id": r.get("winner_team_id"), "status": r.get("status", "pending"),
            "station": r.get("station"), "map": r.get("map"),
        })
    by = {s["mkey"]: s for s in slots}

    # playoff seeds → seed chips + the bye/drop "round-1" boxes that make the
    # format a clean 4->2->1 tree the connectors can line up against.
    try:
        rank_map = {int(k): v for k, v in json.loads(seeding.get_setting("playoff_seeds") or "{}").items()}
    except Exception:
        rank_map = {}
    teamrows = {t["id"]: t for t in db.query_all("SELECT id, name FROM lan_teams")}
    seed_of = {tid: rank for rank, tid in rank_map.items()}

    def _comp(slot, side):
        tid = slot["team_%s_id" % side]
        name = slot["%s_name" % side]
        if not name:  # unresolved — show the source (Seed 3 / Winner QF2 / Loser QF1)
            kind, ref = slot["source_%s" % side].split(":")
            label = {"W": "Winner ", "L": "Loser ", "seed": "Seed "}[kind] + ref
            return {"name": label, "seed": None, "score": None, "win": False, "tbd": True}
        return {"name": name, "seed": seed_of.get(tid), "score": slot["score_%s" % side],
                "win": slot["winner_team_id"] == tid, "tbd": False}

    def _match(mkey):
        s = by[mkey]
        return {"top": _comp(s, "a"), "bottom": _comp(s, "b"), "slot": s,
                "best_of": bracket.BY_KEY[mkey]["best_of"],
                "label": bracket.BY_KEY[mkey]["label"],
                "time": bracket.match_time(mkey), "map": s.get("map")}

    def _t(mkey):
        return bracket.match_time(mkey)

    # Championship — single elim. The Play-in feeds two of the eight QF slots;
    # QF -> SF -> Final is a clean 4->2->1 tree the connectors line up against.
    playin = [_match("PI1"), _match("PI2")]
    champ_rounds = [
        {"title": "Quarterfinals", "time": _t("QF1"), "bo": 3,
         "matches": [_match("QF1"), _match("QF2"), _match("QF3"), _match("QF4")]},
        {"title": "Semifinals", "time": _t("SF1"), "bo": 3, "matches": [_match("SF1"), _match("SF2")]},
        {"title": "Final", "time": _t("F"), "bo": 3, "matches": [_match("F")]},
    ]
    # Consolation / lower bracket — parallel, never feeds the championship.
    consolation_rounds = [
        {"title": "9th / 10th · play-in losers", "time": _t("P910"), "bo": 3, "matches": [_match("P910")]},
        {"title": "Lower semifinals · QF losers", "time": _t("LS1"), "bo": 3, "matches": [_match("LS1"), _match("LS2")]},
        {"title": "Placement finals · 3/4 · 5/6 · 7/8", "time": _t("P34"), "bo": 3,
         "matches": [_match("P34"), _match("P56"), _match("P78")]},
    ]

    def _runner(row):
        if not row or row["status"] != "final" or not row["winner_team_id"]:
            return None
        return row["b_name"] if row["winner_team_id"] == row["team_a_id"] else row["a_name"]

    matches = sched.get_matches()
    ident = ctx["ident"]
    ctx.update(
        generated=bool(db_rows),
        playin=playin,
        champ_rounds=champ_rounds,
        consolation_rounds=consolation_rounds,
        champion=_champ(by.get("F")),
        runner_up=_runner(by.get("F")),
        group_complete=bool(matches) and all(m["status"] == "final" for m in matches),
        comp_maps=sched.COMP_MAPS,
        is_admin=auth.is_admin(request),
        my_team_id=ident["team_id"] if ident else None,
        am_captain=bool(ident and ident["is_captain"]),
        preview=seeding.get_setting("preview_banner") == "1",
        auto_refresh=60,
    )
    return templates.TemplateResponse(request, "bracket.html", ctx)


@router.post("/bracket/report", name="bracket_report")
async def report(request: Request):
    ident = auth.require_login(request)
    form = await request.form()
    mkey = form.get("mkey", "")
    try:
        sa = int(form["score_a"]); sb = int(form["score_b"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Both series scores required.")
    if sa < 0 or sb < 0:
        raise HTTPException(400, "Scores must be non-negative.")
    row = db.query_one("SELECT team_a_id, team_b_id FROM lan_bracket WHERE mkey=%s", (mkey,))
    if not row:
        raise HTTPException(404, "No such bracket match.")
    can = auth.is_admin(request) or (
        ident["is_captain"] and ident["team_id"] in (row["team_a_id"], row["team_b_id"])
    )
    if not can:
        raise HTTPException(403, "Only a captain of one of the two teams (or staff) may report.")
    try:
        bracket.report_series(mkey, sa, sb, actor=ident["discord_id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)


@router.post("/admin/bracket/generate", name="bracket_generate")
def generate(request: Request):
    auth.require_admin(request)
    try:
        bracket.generate_bracket()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)


@router.post("/admin/bracket/station", name="bracket_set_station")
async def set_station(request: Request):
    auth.require_admin(request)
    f = await request.form()
    mkey = f.get("mkey", "")
    if not db.query_one("SELECT 1 FROM lan_bracket WHERE mkey=%s", (mkey,)):
        raise HTTPException(404, "No such bracket match.")
    raw = (f.get("station") or "").strip()
    station = int(raw) if raw.isdigit() and 1 <= int(raw) <= 6 else None
    bracket.set_station(mkey, station)
    if station:
        row = db.query_one(
            "SELECT b.team_a_id, b.team_b_id, ta.name a, tb.name b FROM lan_bracket b "
            "LEFT JOIN lan_teams ta ON ta.id=b.team_a_id LEFT JOIN lan_teams tb ON tb.id=b.team_b_id WHERE b.mkey=%s",
            (mkey,),
        )
        if row and row["team_a_id"] and row["team_b_id"]:
            label = bracket.BY_KEY.get(mkey, {}).get("label", mkey)
            notify.notify_captains(
                [row["team_a_id"], row["team_b_id"]],
                f"\U0001f3ae You're up — {label}: **{row['a']}** vs **{row['b']}** on **Server {station}**. Report to your station.",
            )
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)


@router.post("/admin/bracket/map", name="bracket_set_map")
async def set_map(request: Request):
    auth.require_admin(request)
    f = await request.form()
    mkey = f.get("mkey", "")
    if not db.query_one("SELECT 1 FROM lan_bracket WHERE mkey=%s", (mkey,)):
        raise HTTPException(404, "No such bracket match.")
    # BO3 series can use several maps — collect each picker and join in order.
    maps = [m.strip() for m in f.getlist("map") if m and m.strip()]
    bracket.set_map(mkey, " / ".join(maps)[:96] or None)
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)
