### `scripts/build-game-files-manifest.py`: the stock list is a flag, and it is checked before the connect (2026-09-22)

- #413 gave the generator a `Path(__file__)`-relative data dependency,
  `scripts/data/dod-depot31-stock-paths.txt`, with no way to point at it. That
  breaks the standing recipe for running a pinned copy —
  `git show origin/main:scripts/<name> > /tmp/gen.py && python /tmp/gen.py`
  copies the script and leaves the data directory behind — and it breaks it
  *late*: the list is only read inside `assemble_manifest`, so the
  `FileNotFoundError` landed after the SSH connect and the whole hash pass over
  the live ATL1 tree, throwing the work away.
- `--stock-paths` now names the list, defaulting to the file beside the script,
  and `main()` loads it before `paramiko.SSHClient()` is constructed. The
  failure message says which recipe works (`git archive ... | tar -x`) rather
  than only what is missing — a reader who is told a file is absent tries the
  same broken recipe again.
- Measured on the live API the same day: `/opt/ktp-ac-api/game_files_manifest.json`
  carries `"stock"` **zero** times across 462 entries (control: `"severity"`
  462) and still holds all three PIAT paths, so the served manifest predates
  both #413 and #429 and a regeneration is owed. That regeneration is the first
  run that would have hit this.
