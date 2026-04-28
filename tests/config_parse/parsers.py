"""Small parsers for the four KTP config flavours.

Stdlib-only. Each parser returns a structured form callers can assert
against; none raise on syntactically-OK content. Parse errors propagate
as ValueError with a clear message so test failures point at the line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginEntry:
    line_number: int
    filename: str       # e.g. "KTPMatchHandler.amxx"
    flags: tuple[str, ...]  # e.g. ("debug",) or ()


def parse_plugins_ini(path: Path) -> list[PluginEntry]:
    """Parse a KTPAMXX plugins.ini. Format: one plugin per non-comment,
    non-empty line: `<basename>.amxx [flag1 flag2 ...]`. Comments use `;`."""
    entries: list[PluginEntry] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        filename = parts[0]
        flags = tuple(parts[1:])
        if not filename.endswith(".amxx"):
            raise ValueError(
                f"{path.name}:{lineno}: plugin filename must end with .amxx, got {filename!r}"
            )
        entries.append(PluginEntry(lineno, filename, flags))
    return entries


def parse_modules_ini(path: Path) -> list[str]:
    """Parse a KTPAMXX modules.ini. Format: one module name per non-comment,
    non-empty line. No paths, no extensions — just the bare module name."""
    names: list[str] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if " " in line or "\t" in line or "/" in line or "." in line:
            raise ValueError(
                f"{path.name}:{lineno}: module entry should be a bare name, got {line!r}"
            )
        names.append(line)
    return names


def parse_kv_file(path: Path) -> dict[str, str]:
    """Parse a flat `key = value` config file (discord.ini, hltv_recorder.ini).
    Values may be optionally double-quoted; quotes are stripped. Keys are
    lowercased on read for case-insensitive lookup."""
    out: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"{path.name}:{lineno}: expected `key = value`, got {line!r}")
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if key in out:
            raise ValueError(f"{path.name}:{lineno}: duplicate key {key!r}")
        out[key] = value
    return out


_CFG_LINE_RE = re.compile(r"^\s*(\S+)(?:\s+(.*))?\s*$")


def parse_dodserver_cfg(path: Path) -> dict[str, str]:
    """Parse a Source-engine `cvar value` config (dodserver.cfg).

    Returns the LAST value seen for each cvar (later sets win, matching
    engine semantics). Lines like `exec other.cfg` show up under the key
    `exec` (multiple values lost on collision; kept simple for v1).
    """
    out: dict[str, str] = {}
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("//", 1)[0].strip()
        if not line:
            continue
        m = _CFG_LINE_RE.match(line)
        if not m:
            raise ValueError(f"{path.name}:{lineno}: cannot parse {line!r}")
        cvar, value = m.group(1), (m.group(2) or "").strip()
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        out[cvar.lower()] = value
    return out
