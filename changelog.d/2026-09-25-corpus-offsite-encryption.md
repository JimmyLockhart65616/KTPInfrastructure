### `scripts`: the offsite corpus leg encrypts to a key the data server does not have (2026-09-25)

`ktp-corpus-offsite.sh` shipped the AC replay corpus to the archive box in the
clear, and the bundle filenames went with it. A bundle is player evidence —
SteamIDs, machine names, IPs, screenshots, process and peripheral inventories —
and its filename carries the player and their SteamID, so the directory listing
alone was a roster. The demo and DB legs ship plaintext too; that is right for
them and it was wrong here, and copying their shape is how it happened.

Every bundle is now encrypted with `age` to one or more **public** recipient
keys before it leaves. The private key is never on the data server, never in
`/etc/ktp/offsite.conf` and never on the archive box, so compromising either end
yields ciphertext. Objects land as `<YYYY-MM-DD>/<sha256-of-plaintext>.age`; the
day survives because a restore selects on it and it identifies nobody, and the
name does not. The manifest is the map back and is therefore the most
identifying file in the archive, so it ships encrypted as well.

- **sha256 names the object, md5 stays in the manifest.** An md5 collision
  between two bundles would put them on one remote name and keep whichever
  arrived last — a constructible way to make one piece of evidence overwrite
  another. `md5sum -c` remains the restore idiom the sibling legs already use.
- **The ciphertext cache is content-addressed and written atomically.** Its name
  is the hash of the *plaintext*, so a ciphertext truncated by an interrupted run
  would sit there under a name asserting it was complete and be skipped forever —
  the failure `--checksum` exists to stop on the wire, reintroduced on disk.
- **One recipient warns.** No key means no restore, and the corpus cannot be
  regenerated, so a single key is a single point of permanent loss.
- **A private key in the recipients variable is refused**, not ignored: it would
  both encrypt to the wrong thing and put the key on the one host that must not
  hold it.
- **Dry run stays a read.** It hashes and plans and writes no cache.

Two new scripts, because the half that proves this works was missing. It is not
a detail: the encrypting host holds no key, so it *cannot* verify that what it
wrote is recoverable. It proves arrival; only a restore proves recovery.

- `ktp-corpus-restore.sh` — runs where the key is, which is deliberately not the
  data server. Refuses a non-empty destination, and checks every decrypted
  bundle against the manifest's md5, because `age` authenticates the ciphertext
  it was handed and not that the right ciphertext was stored under that name.
- `ktp-corpus-drill.sh` — the round trip on **synthetic** data: random bytes in
  the real day-dir shape under names that deliberately do not resemble real ones.
  Real evidence is not test data. It asserts the confidentiality claim rather
  than assuming it (no original filename reaches the archive, no object still
  begins with a zip signature) and asserts the negative — a restore with the
  wrong key must fail rather than produce a partial tree that reads as success.

Exercised end to end in WSL: 12 synthetic bundles encrypt, ship, refuse a wrong
key, restore and come back byte-for-byte identical; a second recipient restores
the same archive; a zeroed cache entry is re-encrypted rather than shipped; and
every refusal fires — no recipients, a private key, a malformed recipient, a
destination shared with the demo or DB leg, a cache inside the source.

Not installed and not scheduled. `age` is not on the data server, so the script
refuses there today rather than falling back to plaintext, which is the intended
behaviour and also means it cannot be dry-run there until `age` is installed.
