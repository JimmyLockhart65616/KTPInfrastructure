"""Final placements: the published 1..N order (lan_settings 'final_placements')
plus a best-effort suggestion derived from the bracket + group standings.

The published order is authoritative and admin-owned; the suggestion only
pre-fills the editor — this hybrid format has no single 'correct' auto-ranking."""
from __future__ import annotations

import json


def get_placements() -> list[dict]:
    """Published final order as team rows, or [] if not set."""
    from . import db, seeding
    raw = seeding.get_setting("final_placements")
    if not raw:
        return []
    try:
        ids = json.loads(raw)
    except Exception:
        return []
    teams = {t["id"]: t for t in db.query_all("SELECT id, name, tag, seed FROM lan_teams")}
    return [teams[i] for i in ids if i in teams]


def bracket_champions() -> tuple:
    """(overall champion name, lower-bracket champion name) from the bracket finals.
    Overall champion is the Grand Final winner once decided, else the upper-bracket
    champion as a pre-GF stand-in."""
    from . import bracket as bkt
    rows = {r["mkey"]: r for r in bkt.get_bracket()}

    def champ(mkey):
        r = rows.get(mkey)
        if r and r["status"] == "final" and r["winner_team_id"]:
            return r["a_name"] if r["winner_team_id"] == r["team_a_id"] else r["b_name"]
        return None

    return (champ("GF") or champ("UF")), champ("LF")


def suggested_placements() -> list[int]:
    """Best-effort 1..N order from bracket outcomes, group standings as fallback.
    Only a starting point for the admin editor — never authoritative."""
    from . import db, seeding, standings, bracket as bkt
    from . import schedule as sched
    teams = db.query_all("SELECT id, name, seed FROM lan_teams")
    matches = sched.get_matches()
    standings_order = [r["team"]["id"] for r in standings.compute_standings(teams, matches)] if matches else []
    rows = {r["mkey"]: r for r in bkt.get_bracket()}
    try:
        rank_map = {int(k): v for k, v in json.loads(seeding.get_setting("playoff_seeds") or "{}").items()}
    except Exception:
        rank_map = {}
    seed_of = {tid: rank for rank, tid in rank_map.items()}

    def winner(mkey):
        r = rows.get(mkey)
        return r["winner_team_id"] if r and r["status"] == "final" and r["winner_team_id"] else None

    def loser(mkey):
        r = rows.get(mkey)
        if r and r["status"] == "final" and r["winner_team_id"]:
            return r["team_a_id"] if r["winner_team_id"] == r["team_b_id"] else r["team_b_id"]
        return None

    def by_seed(ids):
        return sorted([i for i in ids if i], key=lambda i: seed_of.get(i, 999))

    # 1-2 from the Grand Final. 3rd = Lower Final loser, 4th = Lower Semifinal
    # loser (positional in true double-elim). Each placement match settles its
    # tier; before it's played, fall back to bracket position ordered by seed,
    # then group standings.
    if winner("GF"):
        order = [winner("GF"), loser("GF")]
    else:
        order = by_seed([winner("UF"), winner("LF")])     # GF entrants, order TBD
    order += [loser("LF"), loser("LSF")]                  # 3rd, 4th
    order += [winner("P56"),  loser("P56")]  if winner("P56")  else by_seed([loser("LB3"), loser("LB4")])
    order += [winner("P78"),  loser("P78")]  if winner("P78")  else by_seed([loser("LB1"), loser("LB2")])
    order += [winner("P910"), loser("P910")] if winner("P910") else by_seed([loser("PA"),  loser("PB")])
    order += standings_order + [t["id"] for t in teams]

    seen, out = set(), []
    for tid in order:
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out
