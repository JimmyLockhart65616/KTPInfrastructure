### `scripts`: regenerating the game-files manifest now says what it changed (2026-09-23)

`build-game-files-manifest.py` opened its output with `"w"` and overwrote it. A regeneration
could therefore widen what the anti-cheat checks every player against, and the only trace was a
manifest version string that had moved. One regeneration added 128 paths and nothing announced
it. Scope is not cosmetic: the client only hashes paths the manifest lists, so an added path is
strictly more enforcement on every player and a removed one is strictly less.

Before writing, the run now prints a scope diff against the manifest already at `--out` — or at
`--baseline`, for the normal review workflow where the candidate is written to a scratch path
and the installed copy is the thing to compare against. It reports the paths added and removed
**grouped by origin**, the totals before and after, the severity flips (`review` → `violation`
widens enforcement without adding a single path), and a count of paths re-hashed in place, which
is the remaining way the version can move.

Grouping is the point rather than a tidiness choice. "12 new paths, all from one map's `.res`"
and "12 new paths across four origins" are different findings and a flat list of twelve paths
does not tell them apart, so `.res`-derived additions also name the maps that referenced them.
The summary survives any size: each origin gets its headline, its severity split and its map
breakdown, then `--diff-limit` paths (10 by default, `0` for all). The failure case that matters
is a large addition, and a wall of output is skipped by the human it exists to inform — which
ends the same way as printing nothing.

⛔ **Advisory only.** It prints; it never refuses, and every baseline problem — absent,
unreadable, not a manifest — comes back as a sentence rather than an exception. Whether a
regeneration should require an acknowledgement is a separate, deliberately separated decision,
to be tuned against a real distribution of diffs rather than off one historical event. Nothing
here pre-empts it.

The baseline is read **before** the write that truncates it, since by default the baseline is
the file being overwritten; reading it late would report every path in the manifest as newly
added, and a diff that cries wolf every run is ignored inside a week.
`tests/unit/test_game_files_manifest_diff.py` covers that ordering through `main()`, along
with the grouping, the severity flips and the large-change readability.

Nothing about the served manifest changes: this is the generator's own reporting, and
regenerating or installing a manifest remains an operator act.
