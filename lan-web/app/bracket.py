"""Sunday playoffs — single-elimination championship + a consolation lower
bracket for final standings, auto-fed from group standings.

Championship (one loss = out of the running): seeds 7-10 play a Play-in, the two
winners join seeds 1-6 (byes) in the Quarterfinals → Semifinals → Final. The
Final winner is the champion; nothing feeds back up.

Lower / consolation bracket (runs in parallel on spare servers, never rejoins
the championship), to give eliminated teams more games and a played-out rank:
- Play-in losers play for 9th/10th.
- The four QF losers drop into a lower semifinal, then play off for 5/6 and 7/8.
- The two SF losers play each other for 3rd/4th.
Every match is BO3. Start times stagger four championship rounds with an hour
break after each — 10:00 AM to ~11:00 PM — and the last placement matches run
alongside the Final, so nothing trails it. 'seed:N' = group rank N,
'W:KEY' = winner, 'L:KEY' = loser."""
from __future__ import annotations

import json

BEST_OF = 3                       # default series length
WINS_NEEDED = BEST_OF // 2 + 1    # 2 (kept for callers; report_series uses per-match best_of)


def wins_for(best_of: int) -> int:
    return best_of // 2 + 1


# Each slot: source 'seed:N' (standings rank), 'W:KEY' (winner of), 'L:KEY' (loser of).
# Championship uses bracket 'upper'; the consolation uses 'placement'.
BRACKET = [
    # Championship — single elim, BO3. Seeds 1-6 bye to the QF; 7-10 play in.
    {"key": "PI1", "bracket": "upper", "stage": "PI", "slot": 1, "a": "seed:7", "b": "seed:10", "best_of": 3, "label": "Play-in 1"},
    {"key": "PI2", "bracket": "upper", "stage": "PI", "slot": 2, "a": "seed:8", "b": "seed:9",  "best_of": 3, "label": "Play-in 2"},
    {"key": "QF1", "bracket": "upper", "stage": "QF", "slot": 1, "a": "seed:1", "b": "W:PI2",   "best_of": 3, "label": "Quarterfinal 1"},
    {"key": "QF2", "bracket": "upper", "stage": "QF", "slot": 2, "a": "seed:4", "b": "seed:5",   "best_of": 3, "label": "Quarterfinal 2"},
    {"key": "QF3", "bracket": "upper", "stage": "QF", "slot": 3, "a": "seed:3", "b": "seed:6",   "best_of": 3, "label": "Quarterfinal 3"},
    {"key": "QF4", "bracket": "upper", "stage": "QF", "slot": 4, "a": "seed:2", "b": "W:PI1",   "best_of": 3, "label": "Quarterfinal 4"},
    {"key": "SF1", "bracket": "upper", "stage": "SF", "slot": 1, "a": "W:QF1", "b": "W:QF2",     "best_of": 3, "label": "Semifinal 1"},
    {"key": "SF2", "bracket": "upper", "stage": "SF", "slot": 2, "a": "W:QF3", "b": "W:QF4",     "best_of": 3, "label": "Semifinal 2"},
    {"key": "F",   "bracket": "upper", "stage": "F",  "slot": 1, "a": "W:SF1", "b": "W:SF2",     "best_of": 3, "label": "Final"},
    # Consolation / lower bracket — BO3, parallel, never feeds the championship.
    {"key": "P34",  "bracket": "placement", "stage": "P34",  "slot": 1, "a": "L:SF1", "b": "L:SF2", "best_of": 3, "label": "3rd / 4th place"},
    {"key": "LS1",  "bracket": "placement", "stage": "LS",   "slot": 1, "a": "L:QF1", "b": "L:QF4", "best_of": 3, "label": "Lower Semifinal 1"},
    {"key": "LS2",  "bracket": "placement", "stage": "LS",   "slot": 2, "a": "L:QF2", "b": "L:QF3", "best_of": 3, "label": "Lower Semifinal 2"},
    {"key": "P56",  "bracket": "placement", "stage": "P56",  "slot": 1, "a": "W:LS1", "b": "W:LS2", "best_of": 3, "label": "5th / 6th place"},
    {"key": "P78",  "bracket": "placement", "stage": "P78",  "slot": 1, "a": "L:LS1", "b": "L:LS2", "best_of": 3, "label": "7th / 8th place"},
    {"key": "P910", "bracket": "placement", "stage": "P910", "slot": 1, "a": "L:PI1", "b": "L:PI2", "best_of": 3, "label": "9th / 10th place"},
]
BY_KEY = {m["key"]: m for m in BRACKET}

# Per-match start times. Four championship rounds, an hour break after each
# (2.5h play + 1h break = 3.5h cadence): 10:00 -> 1:30 -> 5:00 -> 8:30, done
# ~11 PM. Consolation matches run in the same blocks on spare servers; the last
# of them (3/4, 5/6, 7/8) run alongside the Final, so nothing trails it.
MATCH_TIMES = {
    "PI1": "10:00 AM", "PI2": "10:00 AM",
    "QF1": "1:30 PM", "QF2": "1:30 PM", "QF3": "1:30 PM", "QF4": "1:30 PM", "P910": "1:30 PM",
    "SF1": "5:00 PM", "SF2": "5:00 PM", "LS1": "5:00 PM", "LS2": "5:00 PM",
    "F": "8:30 PM", "P34": "8:30 PM", "P56": "8:30 PM", "P78": "8:30 PM",
}


def match_time(mkey: str):
    """Scheduled start time for a bracket match, or None if unknown."""
    return MATCH_TIMES.get(mkey)


# ── pure resolution (no DB; unit-tested) ─────────────────────────────────
def resolve_slots(rank_map: dict[int, int], outcomes: dict[str, tuple]) -> dict[str, tuple]:
    """{rank: team_id} + {mkey: (winner_id, loser_id)} -> {mkey: (a_id, b_id)}.

    A side is None until its source resolves (upstream match undecided)."""
    def side(src):
        if not src:
            return None
        kind, ref = src.split(":")
        if kind == "seed":
            return rank_map.get(int(ref))
        if ref in outcomes:
            w, l = outcomes[ref]
            return w if kind == "W" else l
        return None

    return {m["key"]: (side(m["a"]), side(m["b"])) for m in BRACKET}


# ── DB-backed lifecycle ──────────────────────────────────────────────────
def _rank_map_from_standings():
    from . import db, standings
    from . import schedule as sched
    teams = db.query_all("SELECT id, name, tag, seed FROM lan_teams")
    matches = sched.get_matches()
    incomplete = (not matches) or any(m["status"] != "final" for m in matches)
    st = standings.compute_standings(teams, matches) if matches else []
    return {r["rank"]: r["team"]["id"] for r in st}, incomplete


def _stored_rank_map() -> dict[int, int]:
    from . import seeding
    raw = seeding.get_setting("playoff_seeds")
    return {int(k): v for k, v in json.loads(raw).items()} if raw else {}


def generate_bracket():
    """Freeze the playoff seeding from final standings and lay out the bracket."""
    from . import db, seeding
    rank_map, incomplete = _rank_map_from_standings()
    if len(rank_map) < 10:
        raise ValueError("Need 10 ranked teams — generate and play the group stage first.")
    if incomplete:
        raise ValueError("Group stage isn't complete — every Saturday match must be final first.")
    seeding.set_setting("playoff_seeds", json.dumps(rank_map))
    slots = resolve_slots(rank_map, {})
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lan_bracket")
        for m in BRACKET:
            a, b = slots[m["key"]]
            cur.execute(
                "INSERT INTO lan_bracket (bracket, mkey, stage, slot, source_a, source_b, "
                "team_a_id, team_b_id, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (m["bracket"], m["key"], m["stage"], m["slot"], m["a"], m["b"], a, b),
            )


def get_bracket() -> list[dict]:
    from . import db
    try:
        return db.query_all(
            """
            SELECT b.*, ta.name AS a_name, ta.tag AS a_tag, tb.name AS b_name, tb.tag AS b_tag
            FROM lan_bracket b
            LEFT JOIN lan_teams ta ON ta.id = b.team_a_id
            LEFT JOIN lan_teams tb ON tb.id = b.team_b_id
            ORDER BY FIELD(b.bracket,'upper','placement'),
                     FIELD(b.stage,'PI','QF','SF','F','P34','LS','P56','P78','P910'), b.slot
            """
        )
    except Exception:
        return []


def bracket_exists() -> bool:
    return len(get_bracket()) > 0


def report_series(mkey: str, sa: int, sb: int, actor=None):
    from . import audit, db
    row = db.query_one(
        "SELECT team_a_id, team_b_id, score_a, score_b, winner_team_id, status "
        "FROM lan_bracket WHERE mkey=%s", (mkey,)
    )
    if not row:
        raise ValueError("No such bracket match.")
    if row["team_a_id"] is None or row["team_b_id"] is None:
        raise ValueError("Both teams for this match aren't determined yet.")
    best_of = BY_KEY.get(mkey, {}).get("best_of", BEST_OF)
    need = wins_for(best_of)
    if sa > need or sb > need:
        raise ValueError(f"Best-of-{best_of}: a side can win at most {need}.")
    winner, status = None, "pending"
    if sa >= need or sb >= need:
        winner = row["team_a_id"] if sa > sb else row["team_b_id"] if sb > sa else None
        status = "final" if winner else "live"
    elif sa or sb:
        status = "live"
    db.execute(
        "UPDATE lan_bracket SET score_a=%s, score_b=%s, winner_team_id=%s, status=%s WHERE mkey=%s",
        (sa, sb, winner, status, mkey),
    )
    audit.log("bracket", mkey, "edit" if row["status"] == "final" else "report",
              {"a": row["score_a"], "b": row["score_b"], "winner": row["winner_team_id"], "status": row["status"]},
              {"a": sa, "b": sb, "winner": winner, "status": status}, actor)
    resolve_dependents()


def resolve_dependents():
    """Re-fill W:/L: slots from current final outcomes. Idempotent."""
    from . import db
    rows = {r["mkey"]: r for r in db.query_all("SELECT * FROM lan_bracket")}
    outcomes = {}
    for k, r in rows.items():
        if r["status"] == "final" and r["winner_team_id"]:
            w = r["winner_team_id"]
            l = r["team_a_id"] if w == r["team_b_id"] else r["team_b_id"]
            outcomes[k] = (w, l)
    slots = resolve_slots(_stored_rank_map(), outcomes)
    with db.get_conn() as conn, conn.cursor() as cur:
        for k, (a, b) in slots.items():
            r = rows.get(k)
            if r and (r["team_a_id"] != a or r["team_b_id"] != b):
                cur.execute("UPDATE lan_bracket SET team_a_id=%s, team_b_id=%s WHERE mkey=%s", (a, b, k))


def team_bracket(team_id: int) -> list[dict]:
    """This team's Sunday bracket/placement matches, normalized to us/opponent.
    Already in bracket->stage order from get_bracket()."""
    out = []
    for r in get_bracket():
        if team_id not in (r["team_a_id"], r["team_b_id"]):
            continue
        us_a = r["team_a_id"] == team_id
        m = BY_KEY.get(r["mkey"], {})
        result = None
        if r["status"] == "final" and r["winner_team_id"]:
            result = "W" if r["winner_team_id"] == team_id else "L"
        out.append({
            "label": m.get("label", r["mkey"]),
            "best_of": m.get("best_of", BEST_OF),
            "opponent": r["b_name"] if us_a else r["a_name"],
            "our_score": r["score_a"] if us_a else r["score_b"],
            "opp_score": r["score_b"] if us_a else r["score_a"],
            "result": result, "station": r["station"], "map": r.get("map"),
            "time": match_time(r["mkey"]), "status": r["status"],
        })
    return out


def set_station(mkey: str, station):
    """Admin: assign (or clear) the server/station number for a bracket match."""
    from . import db
    db.execute("UPDATE lan_bracket SET station=%s WHERE mkey=%s", (station, mkey))


def set_map(mkey: str, mapname):
    """Admin: set (or clear) the map(s) for a bracket series."""
    from . import db
    db.execute("UPDATE lan_bracket SET `map`=%s WHERE mkey=%s", (mapname, mkey))


