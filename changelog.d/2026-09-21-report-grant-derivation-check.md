### `scripts`: the report pipeline's grant list is derived from the code, and gated (2026-09-21)

`match_analytics.py`'s `source_capabilities()` asks `information_schema` whether
each optional source exists, and MySQL filters `information_schema` by grant. An
ungranted table is therefore indistinguishable from a table that was never
created: the source is skipped, the report comes out WARN, and it publishes with
no fault recorded anywhere. Measured directly on `neindataatl` — `hlstats_Players`
is present in `hlstatsx`, and `ktpreports` counts zero rows for it in
`information_schema.tables`.

`docs/runbooks/REPORT_PIPELINE_INSTALL.md` carried that list by hand and it went
stale twice: once by being derived at a commit and never re-derived, once by being
derived with a method that could not see the probes. Nothing held either version
to the code.

`scripts/check_report_grants.py` derives the set instead — the table literals
inside `source_capabilities()`, located by `ast` rather than by text match, unioned
with the `FROM`/`JOIN` closure over `report_service.py`, `report_sync.py`,
`report_scope.py`, `match_analytics.py` and `sql/analytics/*.sql` — and compares it
against the runbook's GRANT block (`--source runbook`, no database) and against
`SHOW GRANTS` (`--source live`, on the box). It names the tables rather than
comparing totals, and separates "the grants are wrong" (exit 1) from "this check
answered nothing" (exit 2): a renamed `source_capabilities()`, a missing scanned
file, an empty derived set, an empty `sql/analytics` and an unreachable mysql all
exit 2. Extractor and comparator run against planted fixtures on every invocation,
so a clean result is only reported by a probe that was just shown to work.

Both legs are kept because neither sees the other's defect. On 2026-09-21 the live
grants were complete while the runbook was short five tables, and the runbook is
the rebuild path — a fresh account built from it would have reproduced the silent
degradation on tables that were already fixed live.

Run against `main` at the commit before the hand-fix landed, the check names
exactly the five tables that fix added, and exits 1.

`tests/unit/test_report_grants.py` gates the offline leg in CI, including the case
where a grant is missing, where a grant is unused, and where a written table is
granted read-only.
