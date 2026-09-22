### `analytics`: a player who leaves at half was filed on the opposing team (2026-09-22)

Reported by users against `1789952635-NY1` (underdog vs. very handsom seniors,
2026-09-20): Las1K64 played half 1, subbed out at the break, and the match
report listed him with the opponents — his 41 kills in their totals, the teams
7-vs-6 the wrong way round.

`ktp_match_players.team` is the engine side a player held in the LAST half they
appeared in; the daemon overwrites the row each half. Sides swap at half time,
so a half-1-only player keeps a side that belongs to the other team by the end
of the match. Every consumer that grouped by the roster's team inherited it.

- `scripts/roster_teams.py` derives the canonical team from the per-half life
  feed instead: each half's two side-groups are matched to the final half's by
  player overlap, so the final half's sides stay the canonical labels
  (`game_team` is still the side at match end) and only the misfiled players
  move. `build_report` applies it before anything rolls players up.
- A corrected row keeps the original under `roster_team` (private) so the
  correction is visible rather than silent.
- Measured across everything since 2026-08-31: 16 players in 16 matches, one of
  them official. Control matches are byte-identical — no team assignment changes
  for anyone who played the final half.
- No schema or contract bump: the field already existed and was wrong. Reports
  regenerate with correct teams.
