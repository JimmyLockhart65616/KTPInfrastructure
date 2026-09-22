### `build-game-files-manifest.py`: a `.res` file could widen AC enforcement with no reader on the join (2026-09-22)

The generator treats `maps/*.res` as a manifest source. Producing those files is a
FastDL act with a different owner and a different purpose — a RESGen run over 33 maps
on 2026-09-15 was a download-list deploy — and the next regeneration read its output
as a manifest source and pulled 128 paths into enforcement, at severity `violation`
because that is `severity_for`'s default, as a side effect of a decision nobody made
about the anti-cheat.

Neither half was wrong. The join had no reader: `main()` took no baseline, no diff and
no threshold flag, and wrote `--out` unconditionally. The map-bundle side already
prints its entry-list delta and exits non-zero on a failed self-check; the side where
the consequence lands on a player had no equivalent.

- The generator now diffs **which paths are enforced** against a baseline (default:
  the existing `--out`) and prints added/removed grouped by `origin`, with the
  `referenced_by` maps named on every `.res` addition — the answer to "why is this
  suddenly enforced?" was already in the entry and was never shown.
- A change refuses to write until it is acknowledged by **count**:
  `--accept-added N` / `--accept-removed N`. A count rather than a boolean so it
  expires — a flag that says 128 stops agreeing at 129, which is when someone needs
  to look again. `--accept-added 0` against a real widening refuses, so the cheapest
  thing to paste into a runbook is not the thing that disables the gate.
- Removals gate too. A path leaving enforcement is coverage loss, and a gate watching
  only additions is blind in the direction nobody notices.
- Severity `review` entries are reported but do not gate: captured, never scored, so a
  disclosure change rather than an enforcement one. A changed hash is not a scope
  change either — gating on it would make the gate noise, and noise gets rubber-stamped.
- **The gate runs before anything reaches `--out`.** Writing first and refusing after
  would leave the widened manifest on disk as the next run's baseline, so the second
  run would find nothing added and pass: a refusal laundering itself into an approval.
  A refused run leaves `--out` untouched and writes `<out>.candidate` to read.
- A missing baseline refuses rather than skipping the gate silently
  (`--allow-first-run` to override), and a malformed one raises rather than reading as
  empty — an unreadable baseline read as "nothing to compare" makes every path an
  addition and, once acknowledged, re-baselines the whole manifest as if it had just
  been reviewed.

This is the engineering half only. Whether the `.res`-to-manifest coupling should exist
at all, and who owns the acknowledgement, is an operator question and is carded
separately.

No change to what any generated manifest contains — the gate is entirely about whether
a given regeneration is allowed to install itself.
