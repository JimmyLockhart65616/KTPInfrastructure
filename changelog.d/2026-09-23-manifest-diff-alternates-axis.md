### `scripts`: the manifest scope diff no longer calls an allowed-alternate drop "no change" (2026-09-23)

The scope diff added to `build-game-files-manifest.py` compared three things: which paths are in
the manifest, what severity they carry, and whether their bytes were re-hashed. There is a fourth,
and it is the one that reads as nothing.

`allowed_alternate_hashes` is an operator-curated list of hashes a legitimate community copy of a
file is allowed to match. It is what stops the four entries of the league score-event sound pack —
present on essentially every real player's install — surfacing as false-positive violations.
**Drop one and every holder of that file becomes a violation: no path added, no severity moved, no
hash changed.** The diff had no field for it, so such a regeneration printed

```
  no change: same paths, same severities, same hashes
```

which is the single worst change this reporting exists to catch, described in reassuring words. An
advisory that is silent is merely useless; one that actively reassures is worse than absent.

`diff_manifests` now compares alternates alongside severity and hash, over the same both-sides
population, so nothing is double-counted against a path already reported as added or removed. Every
change is listed under `ALTERNATES CHANGED`, per path and per hash, and never truncated by
`--diff-limit`: the curated set is a handful of hand-made decisions, each one about whether a
legitimate file starts failing, and a count cannot be acted on.

Which direction reaches a player depends on when the path is enforced, and the test differs per
direction. A **drop** starts scoring against holders only if the path is enforced *afterwards*; a
**gain** gives up coverage only if it was enforced *before*. Reading one severity for both would
announce "now scores against every holder" about a path that is `review` afterwards, where nothing
can score — and on a codebase whose own rule is that a check firing on noise gets rubber-stamped,
being wrong in the message is the cost. A drop arriving together with `review` → `violation` is two
widenings at once and is reported as the widening it is.

The `SEVERITY CHANGED` line now carries the caveat that belongs with it: `_meta.version` hashes
path, sha256 and alternates, so **a severity-only regeneration writes a new manifest under an
unchanged version string**. That was in the runbook and nowhere near the finding it qualifies.

⛔ **Still advisory, by ruling — it prints, it never refuses.** No flag was added to the generator
and no exit code changed.

The install gate merged alongside this (`install-game-files-manifest.py`) had computed the same
transitions for itself, its docstring saying it did so "because the diff has no field for it". That
field now exists, so `alternate_transitions` reads it instead of re-walking both manifests — one
comparison behind the report and the refusal, which is what the rest of that gate already does for
paths and severity. Its predicate, its flags and its 2x2 matrix are unchanged. `format_alternate_verdict`
became a classification line for the same reason `format_severity_verdict` is one: the hashes are
listed once, above, and an operator reading one change in two layouts has to work out whether it is
one finding or two.

🔑 **The gate still decides from the transitions, never from the diff's text.** Rewording the
generator's section leaves every refusal test passing and fails only the test that pins the wording —
checked by mutation, because a refusal coupled to a phrase would be silently disarmed by a later
rewrite, which is worse than the defect being fixed here.

`tests/unit/test_game_files_manifest_diff.py` pins the drop, the gain, the per-hash listing, the
asymmetric direction test, the both-sides population, the "no change" wording, the version caveat,
and that `--diff-limit` never hides an alternate.

Nothing about the served manifest changes: this is the generator's own reporting, and regenerating
or installing a manifest remains an operator act.
