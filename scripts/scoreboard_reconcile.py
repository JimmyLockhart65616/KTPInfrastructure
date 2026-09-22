#!/usr/bin/env python3
"""Reconcile a captain's end-of-round scoreboard against the captured stats.

Built for the manual stats check: give it what the screenshot says and what
the database says, and it prints one table per half with a verdict per cell,
so the reviewer reads differences instead of hunting for them.

THE FOUR RULES IT ENCODES (handover/SCOREBOARD_ALIGNMENT_MODEL_20260922.md,
proven against both halves of 1789348403-ATL2):

  Kills     hlstats_Events_Frags, as-is.
  Deaths    hlstats_Events_Frags + hlstats_Events_Teamkills +
            hlstats_Events_Suicides, as victim. The three tables are DISJOINT:
            on the worked match no teamkill or suicide shares a victim and a
            second with a frag row, so they add rather than overlap. The
            report shows the tk/su share of a player's deaths, because a
            death by a friend's bullet is worth seeing.
  ObjScore  SUM(captures x that flag's cap_points). NOT ktp_match_stats.score,
            which carries the dodx savedScore undercount (warmup points
            subtracted once, so half 1 reads low). Both are printed: `stored`
            is shown only to make the defect visible.
  Scope     Player rows are PER HALF — they reset at halftime. The team score
            line is CUMULATIVE, so half 2's team line is the match total.
  Window    The half opens at the ROUND RESTART, not at context_live. DoD
            restarts a few seconds after the live command and the scoreboard
            zeroes there, so kills, deaths and captures in between are ours
            and not the screenshot's. The restart is observable — every player
            respawns at one game_time — so the first >=8-player spawn burst of
            the half IS the zero. This was the whole of the residual
            disagreement: four deaths, two kills and two captures on
            1789348403-ATL2, and 422 frag rows across 203 production matches.

Two inputs, because there are two different jobs:

  --template-csv   a CSV prefilled with the roster for that match, one row per
                   player per half, three blank numbers to fill. For a human
                   doing a manual review (hello chi): you cannot typo a name,
                   and the file is the record of what the screenshot said.
  --template       the JSON shape, for a tool (an OCR pass) to emit.

TRANSCRIPTION IS NOT RECONCILIATION. A wrong digit read off an image and a
genuine stats defect look identical in the output, so the board carries a
`transcription` block saying how the numbers were obtained and whether a
human has checked them. An unverified machine transcription is reported as
provisional and --strict refuses it: an admin eyeballs the image against the
read first, and only then is a difference evidence about the stats.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

SQL = """-- scoreboard_reconcile.py --stats input, for {match_id}
--
-- The window opens at the ROUND RESTART, not at context_live. DoD restarts the
-- round a few seconds after the live command and the scoreboard zeroes there,
-- so anything killed in between is on our side of the line and not on the
-- screenshot. The restart is observable: every player respawns at one
-- game_time, so the first >=8-player spawn burst of the half IS the zero.
-- Measured across production: 422 frag rows in 203 matches sit before it.
-- (A mid-half burst is a cap-out restart, which does NOT reset the player
-- rows -- hence MIN per half, never the latest.)
WITH live AS (
  SELECT match_id, half, MIN(game_time) burst_gt, MIN(event_time) burst_time
  FROM (SELECT match_id, half, game_time, MIN(event_time) event_time
        FROM ktp_life_events
        WHERE match_id = '{match_id}'
          AND boundary_kind = 'start' AND reason = 'spawn'
        GROUP BY match_id, half, game_time
        HAVING COUNT(*) >= 8) b
  GROUP BY match_id, half
)
SELECT s.half, p.player_name,
       COALESCE(f.kills, 0)                        AS kills,
       COALESCE(d.deaths, 0)                       AS deaths,
       COALESCE(t.tk_deaths, 0)                    AS tk_deaths,
       COALESCE(u.suicides, 0)                     AS suicides,
       COALESCE(c.caps, 0)                         AS caps,
       COALESCE(c.cap_points, 0)                   AS objscore,
       s.score                                     AS objscore_stored
FROM ktp_match_stats s
JOIN ktp_match_players p ON p.match_id = s.match_id AND p.player_id = s.player_id
LEFT JOIN (SELECT e.half, e.killerId pid, COUNT(*) kills FROM hlstats_Events_Frags e
           LEFT JOIN live w ON w.half = e.half
           WHERE e.match_id = '{match_id}'
             AND (w.burst_gt IS NULL
                  OR (e.game_time IS NOT NULL AND e.game_time >= w.burst_gt)
                  OR (e.game_time IS NULL AND e.eventTime >= w.burst_time)) GROUP BY 1, 2) f
       ON f.half = s.half AND f.pid = s.player_id
LEFT JOIN (SELECT e.half, e.victimId pid, COUNT(*) deaths FROM hlstats_Events_Frags e
           LEFT JOIN live w ON w.half = e.half
           WHERE e.match_id = '{match_id}'
             AND (w.burst_gt IS NULL
                  OR (e.game_time IS NOT NULL AND e.game_time >= w.burst_gt)
                  OR (e.game_time IS NULL AND e.eventTime >= w.burst_time)) GROUP BY 1, 2) d
       ON d.half = s.half AND d.pid = s.player_id
-- NULL-SAFE ON PURPOSE. Some frag rows carry no game_time at all (2 of 535
-- in the worked match), and `NULL >= x` is NULL, so a naive predicate drops
-- them silently -- it cost two real mid-round kills the first time. Those
-- rows fall back to the wall clock.
-- Teamkills and suicides carry no game_time, so they are cut on the wall clock.
-- One-second granularity: a teamkill inside the restart second counts.
LEFT JOIN (SELECT e.half, e.victimId pid, COUNT(*) tk_deaths FROM hlstats_Events_Teamkills e
           LEFT JOIN live w ON w.half = e.half
           WHERE e.match_id = '{match_id}'
             AND (w.burst_time IS NULL OR e.eventTime >= w.burst_time) GROUP BY 1, 2) t
       ON t.half = s.half AND t.pid = s.player_id
LEFT JOIN (SELECT e.half, e.playerId pid, COUNT(*) suicides FROM hlstats_Events_Suicides e
           LEFT JOIN live w ON w.half = e.half
           WHERE e.match_id = '{match_id}'
             AND (w.burst_time IS NULL OR e.eventTime >= w.burst_time) GROUP BY 1, 2) u
       ON u.half = s.half AND u.pid = s.player_id
LEFT JOIN (SELECT fc.half, fc.player_id pid, COUNT(*) caps,
                  SUM(COALESCE(fp.points_for_cap, 1)) cap_points
           FROM ktp_flag_captures fc
           LEFT JOIN (SELECT map_name, flag_name, MIN(points_for_cap) points_for_cap
                      FROM ktp_flag_positions WHERE points_for_cap IS NOT NULL
                      GROUP BY map_name, flag_name) fp
                  ON fp.flag_name = fc.flag_name
                 AND fp.map_name = (SELECT MAX(map_name) FROM ktp_matches
                                    WHERE match_id = '{match_id}')
           LEFT JOIN live w ON w.half = fc.half
           -- Captures need the same window: the worked match credits two
           -- players a 2-point flag TWO SECONDS before the restart, and the
           -- scoreboard zeroes it with everything else.
           WHERE fc.match_id = '{match_id}'
             AND (w.burst_time IS NULL OR fc.event_time >= w.burst_time)
           GROUP BY 1, 2) c
       ON c.half = s.half AND c.pid = s.player_id
WHERE s.match_id = '{match_id}' AND s.half IN (1, 2)
ORDER BY s.half, p.player_name;
"""

CSV_HEADER = "half,side,player,objscore,kills,deaths"

TEMPLATE = {
    "match_id": "1789348403-ATL2",
    "source": "captain end-of-round screenshots, half 1 and half 2",
    "transcription": {"method": "manual", "by": "chi", "verified": True},
    "halves": {
        "1": {
            "team_score": {"allies": 25, "axis": 69},
            "players": [
                {"name": "o8-[_TillJim_]", "side": "allies",
                 "objscore": 5, "kills": 24, "deaths": 27},
            ],
        }
    },
}


def normalise(name: str) -> str:
    """Match names across the two sources without being fooled by tag noise."""
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def read_text_tolerant(path: Path) -> str:
    """Player names carry odd glyphs and a reviewer's editor may not save UTF-8."""
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def read_board(path: Path) -> dict:
    """A board is JSON from a tool, or CSV from a person. Same shape after this."""
    if path.suffix.lower() != ".csv":
        return json.loads(read_text_tolerant(path))

    halves: dict[str, dict] = {}
    transcription = {"method": "manual", "verified": True}
    match_id = path.stem
    for raw in read_text_tolerant(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            # `# match_id: X` and `# by: name` are carried, everything else is a note.
            key, _, value = line.lstrip("# ").partition(":")
            if key.strip() == "match_id" and value.strip():
                match_id = value.strip()
            elif key.strip() == "by" and value.strip():
                transcription["by"] = value.strip()
            continue
        if line.replace(" ", "").startswith("half,"):
            continue
        # csv, not split(","): a spreadsheet quotes a name that contains one.
        parts = [c.strip() for c in next(csv.reader([line]))]
        if len(parts) < 6:
            raise SystemExit(f"{path}: need 6 columns ({CSV_HEADER}), got: {raw!r}")
        # An unquoted comma in a name splits it; the extra fields are still the name.
        half, side, name = parts[0], parts[1], ", ".join(parts[2:-3])
        objscore, kills, deaths = parts[-3:]
        if not (objscore and kills and deaths):
            continue  # a row left blank is a row not yet transcribed, not a zero
        halves.setdefault(half, {"players": []})["players"].append({
            "name": name, "side": side,
            "objscore": int(objscore), "kills": int(kills), "deaths": int(deaths)})
    if not halves:
        raise SystemExit(f"{path}: no filled rows")
    return {"match_id": match_id, "source": f"transcribed from {path.name}",
            "transcription": transcription, "halves": halves}


def template_csv(stats: dict, match_id: str) -> str:
    """Prefill the roster so the reviewer types numbers, never names."""
    lines = [f"# match_id: {match_id}", "# by: <your name>",
             "# Fill objscore, kills and deaths from the end-of-round screenshot.",
             "# Player rows are THAT HALF only - the scoreboard resets at halftime.",
             "# Leave a row blank if the screenshot does not show it.",
             CSV_HEADER]
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for (half, _), row in sorted(stats.items(), key=lambda kv: (kv[0][0], kv[1]["player_name"])):
        writer.writerow([half, "", row["player_name"], "", "", ""])
    lines.append(buffer.getvalue().rstrip("\n"))
    return "\n".join(lines) + "\n"


def read_stats(path: Path) -> dict:
    rows = [line.rstrip("\n").split("\t")
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"{path} is empty")
    header, body = rows[0], rows[1:]
    out: dict[tuple[str, str], dict] = {}
    for row in body:
        r = dict(zip(header, row))
        if r.get("half") in (None, "half"):
            continue
        out[(str(r["half"]), normalise(r["player_name"]))] = {
            "player_name": r["player_name"],
            "kills": int(r["kills"]), "deaths": int(r["deaths"]),
            "tk_deaths": int(r.get("tk_deaths", 0) or 0),
            "suicides": int(r.get("suicides", 0) or 0),
            "caps": int(r.get("caps", 0) or 0),
            "objscore": int(r["objscore"]),
            "objscore_stored": int(r.get("objscore_stored", 0) or 0),
        }
    return out


def breakdown(row: dict) -> str:
    """Say which of the three tables a player's deaths came from, when it is not all frags."""
    parts = []
    if row["tk_deaths"]:
        parts.append(f"{row['tk_deaths']} tk")
    if row["suicides"]:
        parts.append(f"{row['suicides']} su")
    return " + ".join(parts)


def verdict(shot: int | None, have: int | None) -> str:
    if shot is None or have is None:
        return "—"
    if shot == have:
        return "ok"
    return f"**{have - shot:+d}**"


def reconcile(board: dict, stats: dict) -> tuple[list[str], int]:
    lines: list[str] = []
    differences = 0
    lines.append(f"# Scoreboard reconciliation — {board['match_id']}")
    lines.append("")
    lines.append(f"Screenshot source: {board.get('source', 'unstated')}")
    transcription = board.get("transcription") or {}
    method = transcription.get("method", "unstated")
    verified = bool(transcription.get("verified"))
    who = transcription.get("by")
    lines.append(f"Transcription: {method}"
                 + (f", by {who}" if who else "")
                 + (", verified against the image" if verified else ", **NOT yet verified**"))
    if not verified:
        lines.append("")
        lines.append("> ⚠️ The numbers on the left were not confirmed against the image by a "
                     "person. A difference below may be a misread digit rather than a stats "
                     "defect — check the cell on the screenshot before treating it as either.")
    lines.append("")
    for half in sorted(board["halves"]):
        h = board["halves"][half]
        lines.append(f"## Half {half}")
        lines.append("")
        lines.append("| player | side | K shot | K db | | D shot | D db | | of which tk/su | Obj shot | Obj db | | Obj stored |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for player in h["players"]:
            key = (str(half), normalise(player["name"]))
            row = stats.get(key)
            if row is None:
                lines.append(f"| {player['name']} | {player.get('side','')} | "
                             f"{player['kills']} | — | ⚠ | {player['deaths']} | — | ⚠ | — | "
                             f"{player['objscore']} | — | ⚠ | — |")
                differences += 1
                continue
            vk = verdict(player["kills"], row["kills"])
            # A death is a frag row, a teamkill row or a suicide row. The three
            # tables are DISJOINT — verified on the worked match: no teamkill or
            # suicide shares a victim and a second with a frag — so they add.
            deaths_db = row["deaths"] + row["tk_deaths"] + row["suicides"]
            vd = verdict(player["deaths"], deaths_db)
            vo = verdict(player["objscore"], row["objscore"])
            differences += sum(1 for v in (vk, vd, vo) if v != "ok")
            stored = (f"{row['objscore_stored']}"
                      + (" ⚠" if row["objscore_stored"] != row["objscore"] else ""))
            lines.append(
                f"| {player['name']} | {player.get('side','')} | "
                f"{player['kills']} | {row['kills']} | {vk} | "
                f"{player['deaths']} | {deaths_db} | {vd} | "
                f"{breakdown(row) or ''} | "
                f"{player['objscore']} | {row['objscore']} | {vo} | {stored} |")
        lines.append("")
        team = h.get("team_score")
        if team:
            lines.append(f"Team line on the screenshot: Allies {team['allies']} / "
                         f"Axis {team['axis']}"
                         + (" — cumulative, so this is the MATCH total"
                            if str(half) != "1" else "")
                         + ". Compare against `ktp_team_score_observations`; the "
                           "player rows above are this half only.")
            lines.append("")
    lines.append("---")
    lines.append("")
    if differences:
        lines.append(f"**{differences} difference(s).** A `+n` means the database is higher than "
                     "the screenshot.")
        lines.append("")
        lines.append("- `Obj stored ⚠` — dodx's own score disagrees with captures x cap points. "
                     "Expected in half 1 (savedScore undercount); the computed column is the "
                     "correct one, and it is what the box score should show.")
        lines.append("- Deaths are frag rows + teamkill rows + suicide rows, which are "
                     "disjoint sources rather than overlapping ones; the tk/su column says "
                     "how a player's deaths break down when it is not all frags.")
        lines.append("- Everything is counted from the ROUND RESTART (the half's first "
                     "mass respawn), not from context_live. A difference of one or two on a "
                     "single player is most often a kill or capture in that gap.")
    else:
        lines.append("**No differences.** Every kill, death and objective point on the "
                     "screenshot is reproduced by the captured stats.")
    return lines, differences


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", type=Path,
                    help="scoreboard JSON (--template) or CSV (--template-csv)")
    ap.add_argument("--stats", type=Path, help="TSV from the query --sql prints")
    ap.add_argument("--sql", metavar="MATCH_ID", help="print the stats query and exit")
    ap.add_argument("--template", action="store_true", help="print a board skeleton and exit")
    ap.add_argument("--template-csv", metavar="MATCH_ID",
                    help="print a roster-prefilled CSV for a human reviewer (needs --stats)")
    ap.add_argument("--out", type=Path, help="write the report here (default: stdout)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when anything differs")
    args = ap.parse_args(argv)

    if args.sql:
        print(SQL.format(match_id=args.sql))
        return 0
    if args.template:
        print(json.dumps(TEMPLATE, indent=2))
        return 0
    if args.template_csv:
        if not args.stats:
            ap.error("--template-csv needs --stats (the roster comes from it)")
        sys.stdout.write(template_csv(read_stats(args.stats), args.template_csv))
        return 0
    if not args.board or not args.stats:
        ap.error("--board and --stats are both required (or use --sql / --template)")

    board = read_board(args.board)
    stats = read_stats(args.stats)
    lines, differences = reconcile(board, stats)
    text = "\n".join(lines) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out} ({differences} difference(s))")
    else:
        sys.stdout.write(text)
    unverified = not (board.get("transcription") or {}).get("verified", False)
    if args.strict and unverified:
        print("refusing to pass an unverified transcription: have an admin check the "
              "read against the image, then set transcription.verified", file=sys.stderr)
        return 1
    return 1 if (differences and args.strict) else 0


if __name__ == "__main__":
    raise SystemExit(main())
