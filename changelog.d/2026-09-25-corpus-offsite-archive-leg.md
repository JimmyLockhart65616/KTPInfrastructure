### `scripts`: the AC replay corpus gets a third destination, off the game fleet (2026-09-25)

`scripts/ktp-corpus-offsite.sh` copies `/opt/ktp-ac-api/uploads` to the shell-less archive
box, alongside the demo archive and the DB dumps that already go there. The corpus had two
provider-diverse copies and still had a gap: both of them are production game servers, which
get rebuilt and reconfigured as ordinary ops and one of which was deleted outright in July.
The corpus is evidence that cannot be regenerated and it gates every detection change through
corpus-replay, so it needed a copy whose lifetime is not the fleet's.

- **Its own destination key, `KTP_OFFSITE_RSYNC_CORPUS_DIR`,** and the script refuses to start
  if that path equals the demo or DB one. A conf line added by copying the demo line is the
  likeliest way this lands in the wrong directory, and the symptom would be two archives
  interleaved in one place with nothing reporting it.
- **Verification is a content claim.** The transfer runs `--checksum` so a bundle truncated
  mid-copy on an earlier run is re-sent rather than skipped forever on a plausible size, and a
  second `rsync -ani --checksum` pass itemises anything whose bytes still differ. The demo leg
  cannot afford that at 33 GB and compares size and mtime instead; at corpus scale both passes
  are cheap, so this one makes the same claim `ktp-db-offsite.sh` does.
- **It prints no bundle filenames.** A bundle is named for the player and their SteamID, and
  this output lands in a log and gets pasted into tickets. Every line is summarised by day-dir,
  including the mismatch report, which counts rather than lists. The per-file manifest does
  carry the names and ships beside the data on the archive box instead — in `md5sum` format, so
  a restore is audited with `md5sum -c` from the root of the restored copy.
- **Dry run is the default and `--commit` moves bytes**, matching `push-corpus.py` and
  `feed-staging.py` rather than the `KTP_*_DRYRUN=1` opt-in the older offsite scripts use.
  Selection is the risky half; a tool nobody has run yet should not have "write" as its
  no-argument behaviour.
- **Selection asserts the shape it expects** — `YYYY-MM-DD/*.zip`, one level deep, which is how
  the AC API writes them — and warns with a count when anything under the source falls outside
  it, rather than silently widening or silently dropping.
- Never deletes on the far side, and refuses an empty selection rather than reporting success
  over one.

**Far-side retention is unbounded and the script's header says so.** Nothing prunes this copy,
and nothing prunes the source either: `ktp-ac-retention.sh`'s upload sweep has been held since
2026-08-16 by operator ruling and runs daily as a verified no-op. An earlier audit's "the source
prunes at 28 days" describes `/opt/ktp-backup.sh` and the DB dumps in `/opt/backups`, not the
corpus.

Deliberately **not installed by this repo** and no timer ships with it — deploying and
scheduling on the production data server is an operator act. Install steps are in the PR.
