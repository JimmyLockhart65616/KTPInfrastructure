"""The report pipeline's grant list must stay derived from the code that reads.

An ungranted table is hidden from `information_schema`, so `source_capabilities()`
reads it as a table that was never created and the report publishes short with no
error. The runbook's grant block is the rebuild path, so it is what this gates.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.check_report_grants import (  # noqa: E402
    CannotRun, RUNBOOK, _FROM_JOIN, _sql_literals, _table_refs, capability_probe_sql,
    compare, cte_names, derive, main, parse_grants, probed_tables, runbook_grants,
    self_check)

PROBE_FIXTURE = """
WITH fixture_cte AS (SELECT 1 FROM fixture_cte_source)
SELECT EXISTS(SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'fixture_probed'),
  (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_name IN ('fixture_in_a', 'fixture_in_b'))
FROM fixture_real JOIN fixture_cte ON 1 = 1
-- FROM fixture_commented
"""


def test_self_check_passes():
    self_check()


def test_probe_extractor_reads_equality_and_in_lists():
    assert probed_tables(PROBE_FIXTURE) == {
        "fixture_probed", "fixture_in_a", "fixture_in_b"}


def test_from_join_extractor_ignores_cte_and_comment_and_metadata_schema():
    found = _table_refs(PROBE_FIXTURE, _FROM_JOIN, cte_names(PROBE_FIXTURE))
    assert found == {"fixture_real", "fixture_cte_source"}


def test_a_docstring_mentioning_a_table_is_not_sql():
    module = '"""Reads rows from ktp_nonexistent_table before insert."""\nX = 1\n'
    assert _sql_literals(module, "fixture") == []


def test_renamed_capability_function_cannot_run():
    with pytest.raises(CannotRun):
        capability_probe_sql("def other():\n    pass\n", "fixture")


def test_capability_function_without_probes_cannot_run():
    with pytest.raises(CannotRun):
        capability_probe_sql("def source_capabilities(db):\n    return {}\n", "fixture")


def test_runbook_grant_block_matches_the_derived_set():
    required, _, _, writes = derive(REPO)
    granted, wildcards, _ = runbook_grants(REPO)
    assert compare(required, writes, granted, wildcards) == [], (
        f"{RUNBOOK} and the pipeline's code disagree; re-derive with "
        "python3 -m scripts.check_report_grants --source runbook")


def test_the_check_names_a_grant_it_is_missing():
    required, _, _, writes = derive(REPO)
    granted, wildcards, _ = runbook_grants(REPO)
    dropped = sorted(required)[0]
    thinned = {t: p for t, p in granted.items() if t != dropped}
    assert compare(required, writes, thinned, wildcards) == [f"NOT GRANTED  {dropped}"]


def test_the_check_names_a_grant_nothing_reads():
    required, _, _, writes = derive(REPO)
    granted, wildcards, _ = runbook_grants(REPO)
    padded = dict(granted, ktp_not_read_by_anything={"SELECT"})
    assert compare(required, writes, padded, wildcards) == [
        "GRANTED, UNUSED  ktp_not_read_by_anything  (SELECT)"]


def test_a_written_table_granted_read_only_is_named():
    required, _, _, writes = derive(REPO)
    assert writes, "nothing parsed as an INSERT target; the write leg sees nothing"
    granted, wildcards, _ = runbook_grants(REPO)
    written = sorted(writes)[0]
    read_only = dict(granted, **{written: {"SELECT"}})
    assert f"WRITTEN, NO INSERT  {written}  (SELECT)" in compare(
        required, writes, read_only, wildcards)


def test_probe_leg_covers_tables_no_python_from_join_names():
    """The leg #490's derivation lacked: probed-only tables appear in no FROM."""
    _, probes, _, _ = derive(REPO)
    from scripts.check_report_grants import PIPELINE_SOURCES, _read

    python_side = set()
    for rel in PIPELINE_SOURCES:
        for literal in _sql_literals(_read(REPO, rel), str(rel)):
            python_side |= _table_refs(literal, _FROM_JOIN, set())
    assert probes - python_side, (
        "every probed table is also named in a Python FROM/JOIN, so this fixture "
        "no longer exercises the gap the probe leg exists to close")


def test_grant_parser_keeps_privileges_and_ignores_the_usage_line():
    tables, wildcards, accounts = parse_grants(
        "GRANT USAGE ON *.* TO `a`@`localhost`\n"
        "GRANT SELECT, INSERT ON `db`.`t` TO `a`@`localhost`\n")
    assert tables == {"t": {"SELECT", "INSERT"}}
    assert not wildcards and accounts == {"a@localhost"}


def test_unparseable_grant_text_cannot_run():
    with pytest.raises(CannotRun):
        parse_grants("nothing here resembles a grant")


def test_cli_exits_clean_on_the_offline_leg():
    assert main(["--repo", str(REPO), "--source", "runbook", "--quiet"]) == 0
