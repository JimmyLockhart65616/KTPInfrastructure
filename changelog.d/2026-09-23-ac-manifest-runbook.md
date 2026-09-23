### `docs`: a runbook for regenerating and installing the AC game-files manifest (2026-09-23)

`build-game-files-manifest.py` decides which files the anti-cheat hashes on every player's
machine, and the procedure for running it existed only as a recipe on an operator's board.
There is no cron and no automated caller — every regeneration is a person choosing to run it,
and the person doing that at 23:00 had nothing written down to follow.

`docs/runbooks/AC_GAME_FILES_MANIFEST.md` writes it down: materialise the script from
`origin/main` into a throwaway workdir with the `git archive` line the script's own fail-fast
names, pull the installed manifest down to serve as the baseline, run, read the diff, install.

Three things it exists to stop.

**The script cannot install anything.** It writes JSON to `--out` and stops; installation is a
separate manual scp plus copy into `/opt/ktp-ac-api/`. A reader who assumes regeneration ships
the result skips the only step that reaches a player, and nothing errors.

**The default `--baseline` is `--out`.** For a review that is the wrong file — a local scratch
artifact of unknown age, when the comparison worth reading is against the copy the fleet is
serving. The runbook makes pulling the installed copy down a numbered step and says to pass
`--baseline` explicitly every time.

**The scope gate's counts expire, and that is why it belongs in a written procedure.** A
pre-install run arms `--gate-scope --accept-added N --accept-removed N`; a wrong `N` refuses
with *"The manifest changed since you looked."* So a gate line copy-pasted out of a runbook
with a stale count fails safe rather than rubber-stamping a widening. The runbook also states
that `N` counts enforced paths only, so `review` entries in the diff will not match it, and
that the first armed run refuses by design because nobody can know `N` beforehand.

Two known gaps are stated rather than solved: a `review` → `violation` severity flip widens
enforcement without adding a path, so the gate is blind to it, and it does not move
`_meta.version` either — the version hash covers paths, hashes and alternates, not severity.
The flip is printed under SEVERITY CHANGED and the check is a human reading it.

Documentation only. No behaviour change to the generator, the manifest, or the API that serves it.
