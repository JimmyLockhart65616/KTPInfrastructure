"""Sunday playoffs — true double-elimination, auto-fed from group standings.

Upper bracket (seeds 1-6): seeds 1-2 bye to the SF, 3-6 into QFs. EVERY upper-
bracket loss drops to the lower bracket — QF losers at LR2, SF losers at LR3,
the Upper Final loser into the Lower Final. So the top seeds keep a second life.
Lower bracket (seeds 7-10 + all upper droppers): single-elim, crowns the lower
champion. Grand Final reunites the two, BO5, no bracket reset.

Nearly everything is BO3 — only the Lower Semifinal stays BO1 (it's the one
match that would push the final past midnight). The Grand Final is BO3, no reset;
optionally the upper champion starts it 1-0 (gf_advantage setting) as the reward
for an undefeated run. Placement matches (5/6, 7/8, 9/10) settle the same-round
eliminations off to the side; 3rd and 4th fall out of the lower final / lower
semifinal positionally. 'seed:N' = group rank N, 'W:KEY' = winner, 'L:KEY' = loser."""
from __future__ import annotations

import json

BEST_OF = 3                       # default series length
WINS_NEEDED = BEST_OF // 2 + 1    # 2 (kept for callers; report_series uses per-match best_of)


def wins_for(best_of: int) -> int:
    return best_of // 2 + 1


# Each slot: source 'seed:N' (standings rank), 'W:KEY' (winner of), 'L:KEY' (loser of).
BRACKET = [
    # Upper bracket — BO3.
    {"key": "QF1",  "bracket": "upper", "stage": "QF",  "slot": 1, "a": "seed:3", "b": "seed:6",  "best_of": 3, "label": "Quarterfinal 1"},
    {"key": "QF2",  "bracket": "upper", "stage": "QF",  "slot": 2, "a": "seed:4", "b": "seed:5",  "best_of": 3, "label": "Quarterfinal 2"},
    {"key": "SF1",  "bracket": "upper", "stage": "SF",  "slot": 1, "a": "seed:1", "b": "W:QF2",   "best_of": 3, "label": "Semifinal 1"},
    {"key": "SF2",  "bracket": "upper", "stage": "SF",  "slot": 2, "a": "seed:2", "b": "W:QF1",   "best_of": 3, "label": "Semifinal 2"},
    {"key": "UF",   "bracket": "upper", "stage": "UF",  "slot": 1, "a": "W:SF1", "b": "W:SF2",    "best_of": 3, "label": "Upper Final"},
    # Lower bracket — BO3 except the Lower Semifinal (BO1). Drops: QF->LB, SF->LB3/4, UF->LF.
    {"key": "PA",   "bracket": "lower", "stage": "LR1", "slot": 1, "a": "seed:7", "b": "seed:10", "best_of": 3, "label": "Play-in A"},
    {"key": "PB",   "bracket": "lower", "stage": "LR1", "slot": 2, "a": "seed:8", "b": "seed:9",  "best_of": 3, "label": "Play-in B"},
    {"key": "LB1",  "bracket": "lower", "stage": "LR2", "slot": 1, "a": "L:QF1", "b": "W:PA",     "best_of": 3, "label": "Lower R2 — 1"},
    {"key": "LB2",  "bracket": "lower", "stage": "LR2", "slot": 2, "a": "L:QF2", "b": "W:PB",     "best_of": 3, "label": "Lower R2 — 2"},
    {"key": "LB3",  "bracket": "lower", "stage": "LR3", "slot": 1, "a": "L:SF1", "b": "W:LB2",    "best_of": 3, "label": "Lower R3 — 1"},
    {"key": "LB4",  "bracket": "lower", "stage": "LR3", "slot": 2, "a": "L:SF2", "b": "W:LB1",    "best_of": 3, "label": "Lower R3 — 2"},
    {"key": "LSF",  "bracket": "lower", "stage": "LR4", "slot": 1, "a": "W:LB3", "b": "W:LB4",    "best_of": 1, "label": "Lower Semifinal"},
    {"key": "LF",   "bracket": "lower", "stage": "LR5", "slot": 1, "a": "L:UF", "b": "W:LSF",     "best_of": 3, "label": "Lower Final"},
    # Grand Final — BO3, no reset (upper champ optionally starts 1-0).
    {"key": "GF",   "bracket": "grand", "stage": "GF",  "slot": 1, "a": "W:UF",  "b": "W:LF",     "best_of": 3, "label": "Grand Final"},
    # Placement — same-round eliminations play off for the tier (BO3).
    {"key": "P56",  "bracket": "placement", "stage": "P56",  "slot": 1, "a": "L:LB3", "b": "L:LB4", "best_of": 3, "label": "5th / 6th place"},
    {"key": "P78",  "bracket": "placement", "stage": "P78",  "slot": 1, "a": "L:LB1", "b": "L:LB2", "best_of": 3, "label": "7th / 8th place"},
    {"key": "P910", "bracket": "placement", "stage": "P910", "slot": 1, "a": "L:PA",  "b": "L:PB",  "best_of": 3, "label": "9th / 10th place"},
]
BY_KEY = {m["key"]: m for m in BRACKET}

# Per-match start times. True double-elim is 6 deep on the championship path, so
# matches stagger rather than share clean global slots. Almost all BO3 (only the
# Lower Semifinal BO1) lands the Grand Final at 9:00 PM (BO3) -> ~11:30 PM finish,
# peak 5 of 6 servers busy. Lower rounds shadow the upper-bracket drops, so their
# BO3 length costs no extra wall-clock until LR3.
MATCH_TIMES = {
    "QF1": "10:00 AM", "QF2": "10:00 AM", "PA": "10:00 AM", "PB": "10:00 AM",
    "P910": "12:30 PM",
    "SF1": "12:30 PM", "SF2": "12:30 PM", "LB1": "12:30 PM", "LB2": "12:30 PM",
    "P78": "3:00 PM",
    "UF": "3:00 PM", "LB3": "3:00 PM", "LB4": "3:00 PM",
    "LSF": "5:30 PM",
    "P56": "5:30 PM",
    "LF": "6:30 PM",
    "GF": "9:00 PM",
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
            ORDER BY FIELD(b.bracket,'upper','lower','grand','placement'),
                     FIELD(b.stage,'QF','SF','UF','LR1','LR2','LR3','LR4','LR5','GF','P56','P78','P910'), b.slot
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


def gf_advantage() -> bool:
    """Whether the Grand Final spots the upper champion a 1-0 map lead."""
    from . import seeding
    return seeding.get_setting("gf_advantage") == "1"
