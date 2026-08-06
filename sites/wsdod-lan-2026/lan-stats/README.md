# Philly LAN 2026 — stats recovery

## What happened

The LAN box's HLStatsX ran with an **unseeded `hlstats_Actions` table**. HLStatsX
resolves each incoming action against that table at ingest; with no definitions,
every `dod_control_point` and `dod_capture_area` event was discarded as it
arrived. Kills, deaths and weapon stats were unaffected — only objectives.

Seeding the table afterwards recovers nothing: HLStatsX processes the log stream
live and never revisits it. Replaying the logs through the daemon would have
re-inserted every frag and weaponstat on top of the existing rows, so the
recovery reads the logs directly instead.

## Files

| | |
|---|---|
| `ktp_match_stats.tsv` | per-player **per-half** kills/deaths/headshots/damage/score, 93 matches |
| `ktp_match_players.tsv` | match roster: steam_id, name, team |
| `lan-log-events.tsv` | capture + match-boundary lines pulled from the HLDS logs |
| `recover_captures.py` | parses the above, attributes each capture to match + half |
| `insert_captures.py` | writes to `hlstatsx_lan` (restored clone, data server) |
| `insert_captures_lanbox.py` | writes the same rows back to the LAN box |

Both targets verified identical: `dod_control_point` 3472 events / 62 players /
64 matches, `dod_capture_area` 2523 / 62 / 63.

## Traps worth keeping

**`half` = 0, 1, 2 in `ktp_match_stats`, and 0 is the match TOTAL.** Verified
`half0 == half1 + half2` for 1108 of 1108 player-match pairs. A naive
`SUM(kills)` doubles every number.

**`KTP_MATCH_START` fires once per half** and names it (`"1st half"` / `"2nd
half"`). Inferring the half from marker order instead put 5,989 of 6,015
captures in half 1 — plausible-looking and wrong, and KTPR is a per-half rate.

**`Team "Axis" triggered a "dod_capture_area"`** lines are team-level events
(1,536 of them). They belong in `TeamBonuses`, not player stats.

**1,783 captures fall outside every match window** — warmup and between-match
play. Excluded deliberately.

## For the next LAN

Seed `hlstats_Actions` when provisioning (721 rows in the fleet DB), and check
`SELECT COUNT(*) FROM hlstats_Events_PlayerActions` is non-zero after the first
match. The failure is silent otherwise — everything else looks healthy.
