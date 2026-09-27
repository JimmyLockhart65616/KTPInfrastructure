### `scripts`: `maps/*.res` leaves manifest scope — the server sends the list, so the client's copy proves nothing (2026-09-27)

A `.res` that names itself becomes a downloadable resource, so FastDL hands it to every player who
joins that map and the generator then hashes it like any other asset. Two were in the installed
manifest (`460a687a4f7ed682`): `maps/dod_harrington.res` and `maps/dod_orange.res` — the only two
`.res` files that reference themselves, and `dod_harrington` is in the live mapcycle.

🔴 **It was about to turn clean players into violations, and the reason it went unnoticed is that
nothing gates it.** Both files were rewritten on the source tree on 2026-09-16 19:18 with no
regeneration behind it, so the installed manifest still expects the previous bytes. Measured over
the 105 scans since that manifest went live: `maps/dod_harrington.res` is **present and matching on
37 scans across 36 distinct players**, `maps/dod_orange.res` on 1. Every one of them is clean today
and becomes a `violation` — which counts toward a verdict — the moment the manifest is regenerated,
because the expected hash moves to the new bytes. GoldSrc does not re-download a file the client
already has, so it does not heal on its own.

A changed `sha256` on a path already in scope is printed under `RE-HASHED` and refused by neither
the generator's `--gate-scope` nor the install gate — stated as a known gap in
`docs/runbooks/AC_GAME_FILES_MANIFEST.md`. That inheritance is right in general, since files
legitimately change on the fleet tree; this is the case where the consequence landed.

**Nothing is lost by excluding it.** The server builds the authoritative resource list and sends it
to the client. A player editing their local copy of a text list of filenames changes neither what
they render nor what the server enforces, so the hash was buying no detection while guaranteeing a
false violation on every map redeploy. The map's own assets stay in scope — the exclusion drops the
list, not what the list is for, and a test pins that.

⚠️ **The rule is an extension, not a path prefix.** `maps/` cannot be the unit: `maps/*.bsp` is
already excluded on its own grounds (hashing cost, documented separately) and a prefix rule would
merge two unrelated decisions into one line. `EXCLUDED_EXTENSIONS` is applied before the hash rather
than filtered after it, so an excluded path costs no SSH round trip on a production game host.

`tests/unit/test_res_file_exclusion.py` — 7 tests. 5 fail against the pre-change generator; the
other 2 are controls that are vacuously true on old code (the fixture check, and "the map's assets
stay in scope"), stated rather than counted as regression evidence.
