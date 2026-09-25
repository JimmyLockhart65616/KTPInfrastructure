### `ops`: the encrypted corpus offsite leg is installed, scheduled and restore-proven (2026-09-25)

`ktp-corpus-offsite.sh` from the previous entry is no longer just merged. `age` is on the data
server, the leg is configured against the archive box that already takes the DB dumps and the demo
archive, the first real run has written and verified 854 bundles, a sample has been pulled back off
the box and decrypted on the operator's workstation, and the schedule sits beside its two siblings
in `/etc/cron.d/ktp-offsite` at 06:00 Sunday.

**The fail-closed path was exercised before anything shipped**, not assumed: with `age` absent the
script refused rather than falling back to plaintext, and every guard fired on the real host — no
recipients, a private key in the recipients variable, a malformed recipient, a cache inside the
source, and a destination equal to the demo or DB directory. The one-recipient case warns and
proceeds, which is what it should do.

**Two recipients, two private halves, neither on the data server.** One on the operator's
workstation beside the code-signing key, one bound for a password manager. The conf carries only the
public halves. `docs/BACKUP_SCOPE.md` §1.1 records the three variables in placeholder form so the
install is recoverable from this repository rather than from one box's disk.

**The drill ran on synthetic data first, twice — once per private half — and the negative with it.**
A restore with a key that is not a recipient exits nonzero, prints why, and leaves an empty
destination; a restore with no key and a restore into a non-empty directory both refuse. Then the
same negative was repeated against the *real* archive: a stranger key cannot read the manifest, so it
never reaches an object.

**The restore is the only thing that closes this, and it closed on an independent number.** Three
day-dirs spanning April to September came back off the archive box and decrypted on the workstation
with each private half in turn. The md5 list of the restored plaintext reproduces, digest for digest,
the list the data server computed from its own source files — so the claim is not "the restore script
agreed with the manifest it also wrote", it is "the bytes on the archive box are the bytes in the
corpus".

Three things real data showed that synthetic data could not:

- **Byte-identical bundles collapse to one object.** Objects are named for the sha256 of the
  plaintext, so duplicate content in one day-dir shares a remote name. 854 bundles wrote 842 objects
  and both numbers are right; the restore handles it because it fetches `sort -u` objects and writes
  every manifest row. Two consequences are now written down in `BACKUP_SCOPE.md` §1.1: the leg's log
  line calls the cache `$COUNT` objects when it holds fewer, and the drill's `OBJS -eq N` assert
  would fail on real data — it passes only because its bundles are random bytes.
- **The selection is clean.** All 854 files under the source are `YYYY-MM-DD/*.zip`, so the
  unselected-file warning stayed silent and had something to be silent about.
- **The second run is cheap.** Nothing re-encrypts, and the checksum pass still makes the full
  content claim over the whole set.

⛔ **What this does NOT install: a scheduled drill.** Nothing in cron decrypts anything, on purpose,
so a wrong recipient or a lost identity file would stay invisible until the corpus was needed. The
drill cannot live here — it needs a private key, and keeping private keys off this host is the whole
design. It is a standing quarterly act on a machine that holds a key, and `BACKUP_SCOPE.md` §5 now
says so rather than leaving it to be inferred from a comment.

⚠️ **All three legs land in the same sub-account**, so one account loss takes the DB dumps, the demo
archive and the corpus together. That was accepted when the destination was ruled, and it is recorded
in §1 rather than left as a thing someone rediscovers.
