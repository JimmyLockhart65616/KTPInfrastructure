### `analytics`: `map_control`/`progression` translated to report-team convention, cap-outs detected (2026-09-22)

- DoD swaps Allies/Axis at halftime, but `map_control` (positional shadow)
  and `progression.flag_differential` labeled their team-1/2 by raw engine
  side (1 = Allies, fixed all match) while every other field in the report
  — `players[].team`, `in_game_result` — uses the roster's terminal-half
  slot. The two conventions only agree in the terminal half, so both blocks
  were silently backwards in half 1 of every two-half match. This is what
  produced a reported "inverted momentum graph" (RenameD*Gaming vs OVER,
  2026-09-20).
- New `scripts/report_team_convention.py`: a translation layer over
  `flag_swing.sides_by_half` (not a second side source).
  `report_team1_engine_side` resolves, per half, which engine side report
  team 1 played; `translate_map_control` and `translate_team_series` apply
  it in `match_analytics.py`'s orchestration, before either block reaches
  `shadow_explorations` — the DTO layer needed no changes, since it already
  reads both as pass-through. A half the resolver can't decide (no
  life-boundary rows, or a genuine mid-half team-swap collection couldn't
  see) is dropped from the block, with a caveat, rather than mislabeled.
- New cap-out detection in `flag_swing.py`: a flag transition that leaves
  one side owning every flag is a completed cap-out (distinct from the
  existing `capout_denied`, which flags a cap that broke an *imminent* one).
  Surfaced as `shadow_explorations.capouts` / public `capouts`:
  `{half, game_time, team}[]`, report-team convention, additive.
- `flag_swing.py`'s own math (the `p_allies()` alive term and `team_sign`
  kill attribution) was already fixed for the same root cause on 2026-09-18
  (KTPInfrastructure#455/#458) — this pass is the remaining presentation
  translation plus cap-outs, not a re-fix of that.
- Schema 18 → 19 (forces a full-season regeneration), DTO contract v1.6.0 →
  v1.7.0 (additive `capouts`; `map_control`/`progression` shapes unchanged,
  values only). Existing reports read `capouts` as unavailable and carry
  the old, backwards half-1 `map_control`/`flag_differential` values until
  regenerated.
