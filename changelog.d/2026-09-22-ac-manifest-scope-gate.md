### `build-game-files-manifest.py`: an opt-in refusal when a regeneration widens AC enforcement (2026-09-22)

The generator treats `maps/*.res` as a manifest source. Producing those files is a
FastDL act with a different owner and a different purpose — a RESGen run over 33 maps
on 2026-09-15 was a download-list deploy — and the next regeneration read its output
as a manifest source and pulled 128 paths into enforcement, at severity `violation`
because that is `severity_for`'s default, as a side effect of a decision nobody made
about the anti-cheat.

The advisory scope diff that reports this shipped separately and prints on every run.
This adds the refusal that can be layered on top of it, for the runs where someone
wants one:

- `--gate-scope` refuses to write until an enforcement change is acknowledged by
  **count**: `--accept-added N` / `--accept-removed N`. A count rather than a boolean
  so it expires — a flag that says 128 stops agreeing at 129, which is when someone
  needs to look again. `--accept-added 0` against a real widening refuses, so the
  cheapest thing to paste into a runbook is not the thing that disables the gate.
  Either `--accept` flag implies `--gate-scope`, so a count can never be handed to a
  gate that is not running.
- Removals gate too. A path leaving enforcement is coverage loss, and a gate watching
  only additions is blind in the direction nobody notices.
- Severity `review` entries are reported but do not gate: captured, never scored, so a
  disclosure change rather than an enforcement one. A changed hash is not a scope
  change either — gating on it would make the gate noise, and noise gets rubber-stamped.
- **The gate runs before anything reaches `--out`.** Writing first and refusing after
  would leave the widened manifest on disk as the next run's baseline, so the second
  run would find nothing added and pass: a refusal laundering itself into an approval.
  A refused run leaves `--out` untouched, writes `<out>.candidate` so the hash pass is
  not thrown away, and exits 2.
- The gate decides on the **same diff** that was just printed, so the count an operator
  is told to paste is the count the gate will check.
- The baseline is resolved and read **before the SSH connect**, so a `--baseline` that
  cannot be read is reported immediately rather than after a full `sha256` pass over
  the game tree on a production host.

**Off by default, deliberately.** The diff stays advisory: no baseline is the normal
case, not an edge — there is no automated caller, and the documented workflow
regenerates to a scratch `--out` from a throwaway workdir, so a missing baseline prints
the "unavailable" line and writes. An armed gate with no baseline writes too, but says
`GATE ARMED BUT NOT RUN` rather than letting a run with nothing to compare against read
as an acknowledged one.

Two things this deliberately does not do, both larger than the generator:

- The default baseline is `--out`, a local scratch artifact that may be months stale.
  The review-worthy comparison is against the installed copy at
  `/opt/ktp-ac-api/game_files_manifest.json`.
- **Nothing gates the install step**, which is where the consequence reaches a player.
  This script cannot install anything — its only write is one local `open(out_path, "w")`
  and its remote commands are reads. Installation is a separate manual copy onto the
  data server. If an acknowledgement gate belongs anywhere, it belongs there.

No change to what any generated manifest contains — the gate is entirely about whether
a given regeneration is allowed to overwrite the file it was pointed at.
