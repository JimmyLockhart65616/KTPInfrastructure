# Runbook: regenerate and install the AC game-files manifest

**What:** `scripts/build-game-files-manifest.py` rebuilds
`game_files_manifest.json` — the list of game files the anti-cheat client
hashes on every player's machine, and the severity each mismatch carries.

**When:** after a map deploy, after a change to manifest policy in the script
or to `ktp_file.ini`, or when someone wants to see what regeneration *would*
do. There is no cron and no automated caller. Every run is a person choosing
to run it.

🔴 **The generator installs nothing.** It writes a JSON file where you point
`--out` and stops. Nothing reaches a player until §5 copies that file onto the
AC API host. A reader who thinks regeneration ships something skips the only
step that does — which is also why the acknowledgement that matters lives in §5
and not in §3b.

---

## 1. Materialise the script from `origin/main`, into a throwaway directory

```bash
mkdir /tmp/manifest-$(date +%Y%m%d) && cd /tmp/manifest-$(date +%Y%m%d)
git archive origin/main \
    scripts/build-game-files-manifest.py \
    scripts/data/dod-depot31-stock-paths.txt | tar -x
```

Never run the copy in a working checkout, and never the copy in `/opt/ktp-infra`
on the data server. Both drift, and the drift is silent: a checkout behind the
merge that added a policy change produces a manifest reflecting the old policy,
with no error and a plausible-looking summary. `origin/main` is the only version
of manifest policy anyone has agreed to.

Take **both** files. The stock-path list is read relative to the script, so a
lone script exits at startup — that message names this same `git archive` line,
which is the recipe it is protecting. Pass `--stock-paths` if you keep the list
somewhere else.

## 2. Pull the installed manifest down first — it is the baseline

```bash
scp root@<data-server>:/opt/ktp-ac-api/game_files_manifest.json ./installed.json
```

**`--baseline` defaults to `--out`, which is the wrong file for a review.** Left
at the default with an `--out` in a scratch directory, the run compares against
whatever local artifact happens to be sitting there — possibly months old,
possibly nothing. The comparison worth reading is against the copy the fleet is
actually serving, and that copy lives on the data server. Pass `--baseline`
explicitly, every time.

With no baseline at all the diff prints one line saying so, and an armed gate
prints `GATE ARMED BUT NOT RUN` and writes anyway. A gate that cannot compare
does not protect anything; this step is what gives it something to compare.

## 3a. Exploratory run — looking, not shipping

```bash
KTP_FLEET_SSH_PASSWORD=... python3 scripts/build-game-files-manifest.py \
    --source-server <atl1-host> \
    --filelist <path>/ktp_file.ini \
    --baseline ./installed.json \
    --out ./candidate.json
```

The scope diff prints on every run and refuses on none — that is ruled, and it
is why you can run this to find out what would happen without arming anything.

- `--source-server` — the game host whose `dod/` tree is read and hashed. Value
  is in the operator's notes; the script's own default is ATL1 :27015.
- `--filelist` — `ktp_file.ini` from `origin/main` of `KTPFileChecker`. **Pass
  it.** The default is resolved relative to the script's location and will not
  find anything from a throwaway workdir.
- SSH password comes from `--ssh-password`, `$KTP_FLEET_SSH_PASSWORD`, or
  `~/.ktp_fleet_ssh_password`, in that order. The run exits before connecting if
  none is set.
- `--diff-limit` — paths spelled out per origin. Pass `0` to list every one when
  the diff is what you are there to read.

## 3b. Pre-install run — arm the gate

If you intend to ship the result, arm the scope gate:

```bash
... --gate-scope --accept-added N --accept-removed N
```

**Expect two runs.** You cannot know `N` beforehand. The first armed run refuses,
names the counts, leaves `--out` untouched, writes the manifest to
`<out>.candidate`, and exits 2. Read the diff, then re-run with the counts it
printed. Each run is a full SSH hash pass over a live game tree, so do not fire
the second one until you have actually read the first one's output.

Either `--accept` flag implies `--gate-scope`, so a count can never be handed to
a gate that is not running. If nothing enforced entered or left scope,
`--gate-scope` alone passes with no counts.

⚠️ **`N` counts *enforced* paths, not the paths the diff lists.** `review`
entries are captured and shown to an admin but never score, so they do not gate.
The ADDED total in the diff can exceed the number the gate wants. Use the number
in the refusal message, not the number in the diff header.

🔑 **The counts expire, and that is the point of writing them down at all.** A
wrong `N` refuses with *"The manifest changed since you looked."* So a line
copy-pasted out of this runbook with last month's count **fails safe**: it stops
agreeing the moment the regeneration would add one more path, which is exactly
when someone needs to look again. An acknowledgement that stayed true forever
would be a decoration.

## 4. Read the diff before you install

An added path is more enforcement on every player; a removed one is less. The
diff groups by origin because "+12, all from one map's `.res`" and "+12 across
four origins" are different findings that a flat list cannot tell apart.

Watch `.res` in particular. Custom-map `.res` files on the source server are an
automatic manifest source, and generating them is a FastDL act with a different
purpose and a different owner. That join is how 128 paths entered enforcement in
one step on 2026-09-15 with nobody deciding to.

## 5. Install — the step that actually changes enforcement

Use `scripts/install-game-files-manifest.py`. It is the copy, with the
acknowledgement attached to it:

```bash
git archive origin/main \
    scripts/install-game-files-manifest.py \
    scripts/build-game-files-manifest.py | tar -x

python3 scripts/install-game-files-manifest.py \
    --manifest ./candidate.json \
    --server <data-server> \
    --reason pre-weapon-kit
```

Take both files — the installer reuses the generator's scope diff, so an
operator who read §4 reads the same layout here rather than learning a second
one.

🔴 **The gate is armed by default here, and that is the difference from §3b.**
The generator's `--gate-scope` is opt-in because a regeneration reaches nobody:
arming it by default would be friction where nothing happens to a player. This
step is the opposite — every successful run of it changes what every player with
the client installed is checked against — so the acknowledgement is on unless
you turn it off.

**Expect two runs, for the same reason as §3b.** The first refuses and names the
counts; re-run with them:

```bash
    --accept-added N --accept-removed N --accept-widened N --accept-narrowed N
```

Four separate counts rather than one total, because they are four different
decisions and a single net figure lets an addition and a removal cancel to zero.
Pass only the ones the refusal asked for — a count for a change that is no longer
in the diff refuses too, since that is the same staleness as a count that is too
low. `--dry-run` stops after the verdict if you want to see it without installing.

⚠️ **`--accept-widened` is the one with no equivalent upstream.** `review` →
`violation` widens what a player is *scored* on without adding a path, so the
generator's membership gate passes it and so does `_meta.version`. Six paths
(`p_garand_l.mdl` and friends) made exactly that flip between the 2026-05-07
manifest and the installed one.

What the script does that the old `scp` + `cp` pair did not:

- **Resolves the target from the API's own config.** `GameFilesManifestPath` in
  `appsettings.json` overrides the compiled-in default, and installing to the
  documented path while the API reads another one is an install that changed
  nothing and reported success.
- **Takes the backup itself**, named `…json.bak-<reason>-<YYYYMMDD>`, before it
  writes anything. `--reason` is required and lands in that filename, so make it
  findable in an `ls` six months from now.
- **Publishes by rename**, staging beside the target rather than in `/tmp`,
  because the rename is only atomic within one filesystem. The API caches on
  mtime alone and serves whatever bytes are there, so the live path must never
  hold a partial document.
- **Reads the file back** and compares its sha256 against what was sent.
- **Declines a byte-identical install** rather than backing a file up against its
  own twin and moving the mtime the cache keys on for no change.

⛔ It writes exactly one file, and every path it touches is the manifest or a
name derived from it. `/opt/ktp-ac-api/` also holds `uploads/` — the evidence
corpus — and `releases/`; nothing here operates on a directory, and neither
should anything you type by hand there.

Keep it `root:root 0644` — the API only reads it. The script sets that.

**No restart.** The cache is keyed on mtime, so the copy is the activation.
Responses carry `Cache-Control: max-age=300`, so allow a few minutes before
concluding a client is on the old copy.

⛔ Do not put the manifest in `/home/dod/distribute/`. That path deploys to all
24 game instances in seconds and syncs deletions. The manifest belongs on the
data server only.

### The break-glass, and the one case that needs it

`--no-gate` installs without acknowledging anything and announces itself in the
output. It is for a first install or a deliberate full re-scope, not a way past a
refusal you did not want to read — the `--accept` counts are the override, and
combining `--no-gate` with one is rejected as contradictory.

**A first install genuinely needs it.** With no manifest on the host there is
nothing to compare against, and this refuses rather than installing: a gate that
cannot compare has not passed. That is a deliberate divergence from the
generator, which warns and writes anyway — right for a local file nobody is
served, wrong for the copy players are enforced against.

## 6. Verify

```bash
ssh root@<data-server> "python3 -c \"import json;m=json.load(open('/opt/ktp-ac-api/game_files_manifest.json'))['_meta'];print(m['version'],m['total_files'],m['by_severity'])\""
curl -sI https://<ac-api-host>/api/game-files-manifest | grep -i etag
```

`_meta.version` is derived from the content, not the clock, so it matching the
version the run printed is good evidence the file you built is the file
installed — but it covers paths, hashes and alternates only, which is why the
command also prints `by_severity`. Check both against the run's summary. A
missing file gives a 404 from the endpoint rather than a stale serve, so check
the endpoint too, not just the disk.

---

## Known gaps — stated, not solved

**A severity flip is invisible to the *generator's* gate.** `review` →
`violation` widens what counts against a player without adding a single path,
and `--gate-scope` in §3b only looks at path membership. It is printed there
under SEVERITY CHANGED and nothing stops you on it. **The install gate in §5
does** — `--accept-widened` — which is the reason the acknowledgement was moved
to the step where the change reaches a player. Nothing was tightened at the
generator: it remains advisory by ruling.

**And it is invisible to `_meta.version` too.** The version hash covers paths,
hashes and allowed alternates; severity is not in it. So a severity-only change
leaves the version string unchanged, and "the version didn't move" is not
evidence that nothing changed — it is not evidence at §6 either, which is why
that step also prints `by_severity`. The ETag is computed over the whole
document and does move, so clients still re-fetch; it is the human check that is
fooled, not the client.

**A backup's mtime is not when the backup was taken.** Some of the copies on the
box were made with a flag that preserved the source's timestamp, so
`…bak-pre-weapon-kit-20260915` carries an mtime from the 14th and the set does
not sort by age. Read the name, not the timestamp. The §5 script writes a fresh
copy, so backups it takes do carry their own time — but the older ones do not,
and both live in the same directory.

**A refused run leaves `<out>.candidate` behind.** It is a real manifest that
nobody acknowledged. Delete it or overwrite it; do not install it because it
happens to be there.
