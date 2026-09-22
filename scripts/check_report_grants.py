#!/usr/bin/env python3
"""Reconcile the report pipeline's MySQL grants against the tables its code reads.

An ungranted table is invisible in `information_schema`, so `match_analytics.py`'s
`source_capabilities()` EXISTS probes read it as a table that was never created:
the optional source is skipped, the report publishes WARN, and nothing reports a
fault. So the grant list is derived here rather than maintained by hand.

Both legs are needed. The probes name tables that appear in no `FROM` or `JOIN`
anywhere in the pipeline's Python, and a capability can be added before the SQL
that consumes it; the `FROM`/`JOIN` closure names the tables the pipeline reads
unconditionally, which are never probed.

  python3 -m scripts.check_report_grants --source runbook   # offline, CI-safe
  python3 -m scripts.check_report_grants --source live      # on the data server
  python3 -m scripts.check_report_grants                    # both

Exit codes are distinct on purpose: 1 means the grants and the code disagree,
2 means the check could not run and answered nothing.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_DISCREPANCY = 1
EXIT_CANNOT_RUN = 2

RUNBOOK = Path("docs/runbooks/REPORT_PIPELINE_INSTALL.md")
CAPABILITY_MODULE = Path("scripts/match_analytics.py")
CAPABILITY_FUNCTION = "source_capabilities"
PIPELINE_SOURCES = (
    Path("scripts/report_service.py"),
    Path("scripts/report_sync.py"),
    Path("scripts/report_scope.py"),
    Path("scripts/match_analytics.py"),
)
SQL_GLOB = ("sql/analytics", "*.sql")

# Schemas a FROM may legitimately name that the account needs no table grant on.
UNGRANTABLE_SCHEMAS = {"information_schema", "performance_schema", "mysql", "sys"}
# Tokens that can follow FROM/JOIN without naming a table.
NOT_A_TABLE = {"dual", "select", "lateral", "unnest"}

_SQL_VERB = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|REPLACE)\b", re.I)
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CTE_NAME = re.compile(r"(?<![.\w`])(\w+)\s+AS\s*\(", re.I)
_FROM_JOIN = re.compile(r"\b(?:FROM|JOIN)\s+(`?\w+`?(?:\s*\.\s*`?\w+`?)?)", re.I)
_INSERT_TARGET = re.compile(r"\bINSERT\s+(?:IGNORE\s+)?INTO\s+(`?\w+`?(?:\s*\.\s*`?\w+`?)?)", re.I)
_PROBE_EQ = re.compile(r"table_name\s*=\s*'([^']+)'", re.I)
_PROBE_IN = re.compile(r"table_name\s+IN\s*\(([^)]*)\)", re.I)
_QUOTED = re.compile(r"'([^']+)'")
_GRANT_LINE = re.compile(
    r"^GRANT\s+(?P<privs>[A-Za-z, ]+?)\s+ON\s+(?P<obj>\S+)\s+TO\s+(?P<acct>\S+@\S+)",
    re.I | re.M,
)


class CannotRun(Exception):
    """The check answered nothing; never let this read as a clean result."""


def _strip_comments(sql: str) -> str:
    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", sql))


def _unqualify(raw: str) -> tuple[str, str]:
    """Split a possibly schema-qualified, possibly backticked object name."""
    parts = [p.strip().strip("`").strip() for p in raw.split(".")]
    if len(parts) == 2:
        return parts[0].lower(), parts[1]
    return "", parts[0]


def cte_names(sql: str) -> set[str]:
    return {m.lower() for m in _CTE_NAME.findall(_strip_comments(sql))}


def _table_refs(sql: str, pattern: re.Pattern[str],
                bound: set[str] | None = None) -> set[str]:
    """`bound` is corpus-wide because match_analytics injects SQL fragments that
    name a CTE defined in another file; per-query binding reads those as tables.
    """
    body = _strip_comments(sql)
    bound = cte_names(sql) if bound is None else bound
    found = set()
    for raw in pattern.findall(body):
        schema, name = _unqualify(raw)
        if schema in UNGRANTABLE_SCHEMAS or name.lower() in NOT_A_TABLE:
            continue
        if not schema and name.lower() in bound:
            continue
        found.add(name)
    return found


def _sql_literals(py_source: str, origin: str) -> list[str]:
    """String literals that are SQL. Prose about reading FROM a table is not."""
    try:
        tree = ast.parse(py_source)
    except SyntaxError as exc:
        raise CannotRun(f"{origin}: could not parse as Python: {exc}") from exc
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None:
                docstrings.add(doc)
    return [
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value not in docstrings and _SQL_VERB.search(node.value)
    ]


def capability_probe_sql(py_source: str, origin: str) -> str:
    """The EXISTS-probe query, located by function rather than by text match."""
    try:
        tree = ast.parse(py_source)
    except SyntaxError as exc:
        raise CannotRun(f"{origin}: could not parse as Python: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == CAPABILITY_FUNCTION:
            literals = [
                child.value for child in ast.walk(node)
                if isinstance(child, ast.Constant) and isinstance(child.value, str)
                and "information_schema" in child.value
            ]
            if not literals:
                raise CannotRun(
                    f"{origin}: {CAPABILITY_FUNCTION}() holds no information_schema "
                    "query; its probes moved and this check no longer sees them")
            return "\n".join(literals)
    raise CannotRun(
        f"{origin}: no function named {CAPABILITY_FUNCTION}(); it was renamed or "
        "moved, and a grant derived without its probes repeats the 2026-09 defect")


def probed_tables(probe_sql: str) -> set[str]:
    body = _strip_comments(probe_sql)
    names = set(_PROBE_EQ.findall(body))
    for group in _PROBE_IN.findall(body):
        names.update(_QUOTED.findall(group))
    return names


def _read(repo: Path, rel: Path) -> str:
    path = repo / rel
    if not path.is_file():
        raise CannotRun(f"{rel} is missing from {repo}; the scan list is stale")
    return path.read_text(encoding="utf-8")


def derive(repo: Path) -> tuple[set[str], set[str], set[str], set[str]]:
    """Tables the pipeline reads: the union, the probed leg, the static leg, the writes."""
    probes = probed_tables(
        capability_probe_sql(_read(repo, CAPABILITY_MODULE), str(CAPABILITY_MODULE)))
    if not probes:
        raise CannotRun(
            f"{CAPABILITY_FUNCTION}() yielded no probed table names; the probe "
            "shape changed and an empty set would pass every comparison")

    sql_dir = repo / SQL_GLOB[0]
    if not sql_dir.is_dir():
        raise CannotRun(f"{SQL_GLOB[0]} is missing from {repo}; the scan list is stale")
    sql_files = sorted(sql_dir.glob(SQL_GLOB[1]))
    if not sql_files:
        raise CannotRun(f"no {SQL_GLOB[1]} under {SQL_GLOB[0]}; nothing was scanned")

    units = [lit for rel in PIPELINE_SOURCES
             for lit in _sql_literals(_read(repo, rel), str(rel))]
    units += [path.read_text(encoding="utf-8") for path in sql_files]

    # A CTE must never shadow a probed table: the probe leg is the authority on
    # which names are real, and a shadowed one would drop out of the grant list.
    bound = set().union(*(cte_names(u) for u in units)) - {p.lower() for p in probes}

    static: set[str] = set()
    writes: set[str] = set()
    for unit in units:
        static |= _table_refs(unit, _FROM_JOIN, bound)
        writes |= _table_refs(unit, _INSERT_TARGET, bound)

    if not static:
        raise CannotRun("the FROM/JOIN closure is empty; the extractor matched nothing")
    return probes | static, probes, static, writes


def _account(raw: str) -> str:
    user, _, host = raw.rstrip(";").partition("@")
    strip = "`'"
    return f"{user.strip().strip(strip)}@{host.strip().strip(strip)}"


def parse_grants(text: str) -> tuple[dict[str, set[str]], set[str], set[str]]:
    """Per-table privileges, the schemas granted wholesale, and the accounts named."""
    tables: dict[str, set[str]] = {}
    wildcards: set[str] = set()
    accounts: set[str] = set()
    for match in _GRANT_LINE.finditer(text):
        privs = {p.strip().upper() for p in match.group("privs").split(",") if p.strip()}
        schema, name = _unqualify(match.group("obj"))
        accounts.add(_account(match.group("acct")))
        if name == "*":
            if schema and schema != "*":
                wildcards.add(schema)
            continue
        tables.setdefault(name, set()).update(privs)
    if not accounts:
        raise CannotRun("no GRANT statement parsed; the grant text was not understood")
    return tables, wildcards, accounts


def runbook_grants(repo: Path) -> tuple[dict[str, set[str]], set[str], str]:
    tables, wildcards, accounts = parse_grants(_read(repo, RUNBOOK))
    if len(accounts) != 1:
        raise CannotRun(
            f"{RUNBOOK} grants more than one account ({sorted(accounts)}); which "
            "one the pipeline uses is no longer derivable from it")
    return tables, wildcards, accounts.pop()


def _os_user() -> str:
    """auth_socket is checked against the OS identity, and mysql sends `root` regardless."""
    try:
        import pwd  # the offline leg still has to run wherever CI puts it
    except ModuleNotFoundError as exc:
        raise CannotRun(
            "no POSIX user database here; the live leg runs on the data server") from exc
    return pwd.getpwuid(os.geteuid()).pw_name


def live_grants(account: str, timeout: int) -> tuple[dict[str, set[str]], set[str]]:
    user, _, host = account.partition("@")
    query = f"SHOW GRANTS FOR '{user}'@'{host}'"
    try:
        proc = subprocess.run(
            ["mysql", "--batch", "--raw", "--skip-column-names",
             f"--user={_os_user()}", "-e", query],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise CannotRun("no mysql client on PATH; run the live leg on the data server") from exc
    except subprocess.TimeoutExpired as exc:
        raise CannotRun(f"{query} timed out after {timeout}s") from exc
    if proc.returncode != 0:
        raise CannotRun(
            f"{query} failed rc={proc.returncode}: {proc.stderr.strip()[-600:]}")
    tables, wildcards, _ = parse_grants(proc.stdout)
    if not any("USAGE" in p for p in tables.values()) and not wildcards \
            and "USAGE" not in proc.stdout.upper():
        raise CannotRun(
            "SHOW GRANTS returned no USAGE line; every account has one, so this "
            "output is not a grant listing")
    return tables, wildcards


def compare(required: set[str], writes: set[str],
            granted: dict[str, set[str]], wildcards: set[str]) -> list[str]:
    faults = []
    covered = set(granted) | (required if wildcards else set())
    for table in sorted(required - covered):
        faults.append(f"NOT GRANTED  {table}")
    for table in sorted(set(granted) - required - {"*"}):
        if granted[table] == {"USAGE"}:
            continue
        faults.append(f"GRANTED, UNUSED  {table}  ({', '.join(sorted(granted[table]))})")
    for table in sorted(writes & covered):
        privs = granted.get(table, set())
        if privs and "INSERT" not in privs and not wildcards:
            faults.append(f"WRITTEN, NO INSERT  {table}  ({', '.join(sorted(privs))})")
    return faults


_CONTROL_SQL = """
WITH ktp_control_cte AS (SELECT 1 AS n FROM ktp_control_from_cte)
SELECT EXISTS(SELECT 1 FROM information_schema.tables
  WHERE table_schema = DATABASE() AND table_name = 'ktp_control_probed') AS probed,
  (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_name IN ('ktp_control_probed_in', 'ktp_control_probed_in2')) AS n
FROM ktp_control_from JOIN ktp_control_cte ON 1 = 1
-- FROM ktp_control_commented
"""
_CONTROL_GRANTS = """
GRANT USAGE ON *.* TO `ktp_control`@`localhost`
GRANT SELECT, INSERT ON `hlstatsx`.`ktp_control_table` TO `ktp_control`@`localhost`
"""


def self_check() -> None:
    """Prove the extractors still see what they claim before trusting a clean result."""
    probes = probed_tables(_CONTROL_SQL)
    expect_probed = {"ktp_control_probed", "ktp_control_probed_in", "ktp_control_probed_in2"}
    if probes != expect_probed:
        raise CannotRun(f"probe extractor self-check failed: {sorted(probes)}")

    static = _table_refs(_CONTROL_SQL, _FROM_JOIN)
    if static != {"ktp_control_from", "ktp_control_from_cte"}:
        raise CannotRun(f"FROM/JOIN extractor self-check failed: {sorted(static)}")

    tables, wildcards, accounts = parse_grants(_CONTROL_GRANTS)
    if tables != {"ktp_control_table": {"SELECT", "INSERT"}} or wildcards \
            or accounts != {"ktp_control@localhost"}:
        raise CannotRun(f"grant parser self-check failed: {tables} {wildcards} {accounts}")

    planted = {"ktp_control_table", "ktp_control_absent"}
    if compare(planted, set(), tables, set()) != ["NOT GRANTED  ktp_control_absent"]:
        raise CannotRun("comparator self-check failed: a missing grant went unreported")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--source", choices=("runbook", "live", "both"), default="both")
    parser.add_argument("--account", default="",
                        help="override the account the runbook names")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    try:
        self_check()
        required, probes, static, writes = derive(args.repo)
        book_tables, book_wildcards, book_account = runbook_grants(args.repo)
        account = args.account or book_account
    except CannotRun as exc:
        print(f"CANNOT RUN: {exc}", file=sys.stderr)
        return EXIT_CANNOT_RUN

    if not args.quiet:
        probe_only = sorted(probes - static)
        print(f"account: {account}")
        print(f"derived tables ({len(required)}):")
        for table in sorted(required):
            marks = "".join(("P" if table in probes else "-",
                             "W" if table in writes else "-"))
            print(f"  {marks}  {table}")
        print("  P = read through an information_schema EXISTS probe "
              "(invisible to a FROM/JOIN grep); W = written")
        print(f"  probed: {len(probes)}; reachable ONLY through a probe: "
              f"{len(probe_only)} {probe_only}")

    faults = []
    if args.source in ("runbook", "both"):
        book = compare(required, writes, book_tables, book_wildcards)
        print(f"\n{RUNBOOK}: {'OK' if not book else str(len(book)) + ' fault(s)'}")
        faults += [f"runbook: {f}" for f in book]

    if args.source in ("live", "both"):
        try:
            live_tables, live_wildcards = live_grants(account, args.timeout)
        except CannotRun as exc:
            print(f"CANNOT RUN: live grants: {exc}", file=sys.stderr)
            return EXIT_CANNOT_RUN
        live = compare(required, writes, live_tables, live_wildcards)
        print(f"SHOW GRANTS FOR {account}: "
              f"{'OK' if not live else str(len(live)) + ' fault(s)'}")
        faults += [f"live: {f}" for f in live]

    if faults:
        print("\nDISCREPANCY", file=sys.stderr)
        for fault in faults:
            print(f"  {fault}", file=sys.stderr)
        print("\nA NOT GRANTED table reads as a table that does not exist: the source "
              "is skipped and the report still publishes.", file=sys.stderr)
        return EXIT_DISCREPANCY

    print("\nOK: every table the pipeline reads is granted, and nothing else is.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
