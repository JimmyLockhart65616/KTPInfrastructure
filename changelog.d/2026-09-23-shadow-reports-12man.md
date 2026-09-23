### Shadow reports: 12-mans are built, never published (2026-09-23)

`generate` discovered only the official types, so the analytics that read a
report — excursions, plays, flag_swing, the hidden-value detector — could not
see a 12-man at all. Two of the three specimens that motivated hidden-value
pricing came from 12-mans and had to be found by hand.

Discovery now runs on `DISCOVERED_MATCH_TYPES` (official + shadow); publication
scope stays `OFFICIAL_MATCH_TYPES`. Nothing downstream needed a second gate:
`classify()` returns `HELD_BY_TYPE` for a match with no official-type half, so
aggregate and `report_sync` hold a shadow report back on the rule they already
apply to a report written by an explicit `--match-ids` run. The test that pins
`match_scope_columns()` to `IN (0, 4)` is what keeps that true.

Shadow set is 12man (2) only. Scrims (1) stay out: the hidden-value review
already discounts scrim play as loose, so building them buys nothing.

Operator-visible: the corpus grows from 18 settled S10 officials to ~81
(63 12-mans since 2026-09-13 carry flag-state events), so the first run after
this lands is long. `generate` now prints the built and held-back type sets on
every run, and a 12-man that fails to build counts in `failures:` like any
other match — `verify_report_pipeline`'s DRAINED check deliberately stays
official-only.
