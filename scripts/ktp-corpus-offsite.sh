#!/bin/bash
# Offsite copy of the AC replay corpus, to the shell-less archive target.
#
# WHY A THIRD DESTINATION. The corpus already goes to two provider-diverse
# hosts (ktp-corpus-push.service / ktp-corpus-push-denver.service, 04:15 and
# 04:45 daily, md5-verified per upload and never deleting). That is not a
# broken setup -- it is two copies on PRODUCTION GAME SERVERS, which are
# rebuilt, reconfigured and occasionally deleted as ordinary ops. The corpus
# is evidence that cannot be regenerated and it gates every detection change
# through corpus-replay, so it needs a copy somewhere the game fleet's
# lifecycle cannot reach. The archive box already holds the demo archive and
# the DB dumps and is the only destination outside the infrastructure we
# routinely modify.
#
# FAR-SIDE RETENTION: UNBOUNDED, ON PURPOSE. This script never deletes, the
# archive box prunes nothing, and neither does the source -- the upload sweep
# in ktp-ac-retention.sh has been held since 2026-08-16 (operator: retain all
# evidence bundles), so a bundle that lands here is kept until someone removes
# it by hand. That is the same accumulate-forever contract the demo and DB legs
# carry, stated rather than left to be inferred: the copy will grow without
# limit and nobody is watching a quota. Whether the box's own automatic
# snapshots are on is a SEPARATE question (docs/BACKUP_SCOPE.md section 2) --
# unbounded retention of the current bytes is not the same as keeping an older
# generation of a bundle something overwrote, and this script does not provide
# the second one.
#
# SHELL-LESS TARGET ONLY. The archive box speaks rsync and SFTP and offers no
# general shell; worse, it accepts a compound command, runs the first token,
# discards the rest and exits 0 (docs/BACKUP_SCOPE.md section 2). Every check
# here therefore goes through the rsync protocol. There is deliberately NO
# shell-capable host list in this script: the two shell-capable destinations
# already have a writer that verifies each upload by md5, and a second writer
# into the same directory would be a duplicate rather than a third copy. If a
# shell-capable target is ever added here it gets its OWN list and its own
# md5 path -- folding it onto this one would silently downgrade it to whatever
# the shell-less path can prove, with nothing saying so.
#
# VERIFICATION IS A CONTENT CLAIM, NOT AN EXIT CODE. The transfer runs with
# --checksum so a bundle truncated mid-copy on an earlier run is re-sent rather
# than skipped forever on a plausible size and a fresh mtime, and a second
# `rsync -ani --checksum` pass then itemises anything whose bytes still differ.
# Both passes read every byte on both sides. The demo leg cannot afford that at
# 33 GB and verifies by size+mtime instead; at corpus scale it is cheap, so
# this script does what ktp-db-offsite.sh does and makes the stronger claim.
#
# IT PRINTS NO BUNDLE FILENAMES. A bundle is named
# KTP_AC_<player>_STEAM_<id>_<timestamp>.zip, so a file list is a list of
# players and their SteamIDs. This output goes to a log and gets pasted into
# tickets and PRs; the ruling that publishing SteamIDs is fine bounds the HUD
# feed and does NOT reach AC evidence. Everything here is summarised by
# day-dir. The per-file manifest, which does carry the names, ships BESIDE the
# data on the archive box, which is where it belongs.
#
# NO HOSTNAMES OR CREDENTIALS IN THIS FILE. This repository is public. Targets
# come from the environment; the script refuses rather than guessing.
#
#   KTP_CORPUS_SRC                 source directory (default below)
#   KTP_OFFSITE_RSYNC_HOSTS        shell-less target(s), user@host
#   KTP_OFFSITE_RSYNC_RSH          transport for those, e.g. ssh with port/key
#   KTP_OFFSITE_RSYNC_CORPUS_DIR   destination directory -- its OWN key, not
#                                  the demo or DB one; sharing a directory
#                                  mixes two archives whose retention and
#                                  restore audiences are different
#
# Run on the data server, where the corpus already is. Dry run is the default;
# it takes --commit to move anything, matching push-corpus.py and
# feed-staging.py, the two tools that already handle this corpus.

set -uo pipefail

SRC="${KTP_CORPUS_SRC:-/opt/ktp-ac-api/uploads}"
RSYNC_HOSTS="${KTP_OFFSITE_RSYNC_HOSTS:-}"
RSYNC_RSH="${KTP_OFFSITE_RSYNC_RSH:-}"
DEST="${KTP_OFFSITE_RSYNC_CORPUS_DIR:-}"

COMMIT=0
for arg in "$@"; do
    [ "$arg" = "--commit" ] && COMMIT=1
done

fail() { echo "[corpus-offsite] FAILED: $*" >&2; exit 1; }

[ -n "$RSYNC_HOSTS" ] || fail "KTP_OFFSITE_RSYNC_HOSTS is unset. Refusing to guess a target."
[ -n "$RSYNC_RSH" ]   || fail "KTP_OFFSITE_RSYNC_HOSTS is set but KTP_OFFSITE_RSYNC_RSH is not."
[ -n "$DEST" ]        || fail "KTP_OFFSITE_RSYNC_CORPUS_DIR is unset. Refusing to guess a path."
# A conf line added by copying the demo one is the likeliest way this lands in
# the wrong directory, and the symptom would be two archives interleaved in one
# place with no error anywhere.
[ "$DEST" != "${KTP_OFFSITE_RSYNC_DIR:-}" ] \
    || fail "KTP_OFFSITE_RSYNC_CORPUS_DIR is the same path as the demo archive (KTP_OFFSITE_RSYNC_DIR)."
[ "$DEST" != "${KTP_OFFSITE_RSYNC_DB_DIR:-}" ] \
    || fail "KTP_OFFSITE_RSYNC_CORPUS_DIR is the same path as the DB dumps (KTP_OFFSITE_RSYNC_DB_DIR)."
[ -d "$SRC" ] || fail "source $SRC does not exist"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
LIST="$WORK/rel.txt"

# ---------------------------------------------------------------- selection
# The AC API writes <guid>_<name>.zip straight into a YYYY-MM-DD day-dir, flat,
# one level deep. Asserting that shape rather than sweeping *.zip recursively
# means a bundle that turns up somewhere else is REPORTED instead of quietly
# widening what this copies.
find "$SRC" -mindepth 2 -maxdepth 2 -type f -name '*.zip' ! -name '.*' -printf '%P\n' \
    | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}/' \
    | sort > "$LIST"
COUNT=$(wc -l < "$LIST")
[ "$COUNT" -gt 0 ] || fail "selection matched no bundles -- refusing to 'succeed' with an empty set"

# Anything under the source the selection did NOT pick up. A bundle in the
# wrong shape is one that never leaves this host, and the only sign of it would
# be a count nobody was comparing against anything.
TOTAL_FILES=$(find "$SRC" -type f ! -name '.*' | wc -l)
UNSELECTED=$(( TOTAL_FILES - COUNT ))
if [ "$UNSELECTED" -ne 0 ]; then
    echo "[corpus-offsite] WARNING: $UNSELECTED file(s) under $SRC are not YYYY-MM-DD/*.zip and are NOT being copied" >&2
fi

# du -c reports KILOBYTES. The demo script once labelled this same figure "MB"
# when it was GB; keep both units so a wrong one is visible rather than plausible.
KB=$( cd "$SRC" && tr '\n' '\0' < "$LIST" | du -c --files0-from=- 2>/dev/null | tail -1 | cut -f1 )
# An unset or empty KB becomes 0 in bash arithmetic, and "0 MB" alongside a
# healthy file count reads as a small corpus rather than as a sizing step that
# did not run.
[ "${KB:-0}" -gt 0 ] 2>/dev/null \
    || fail "$COUNT bundle(s) matched but du sized them at nothing -- refusing to report a size that was never measured"
DAYS=$(cut -d/ -f1 "$LIST" | sort -u)
DAY_COUNT=$(printf '%s\n' "$DAYS" | wc -l)
echo "[corpus-offsite] selected $COUNT bundle(s) ($(( KB / 1024 )) MB / $(( KB / 1024 / 1024 )) GB)"
echo "[corpus-offsite] $DAY_COUNT day-dir(s), $(printf '%s\n' "$DAYS" | head -1) .. $(printf '%s\n' "$DAYS" | tail -1)"

# A manifest shipped BESIDE the bundles. md5sum output format, so a restore is
# audited with `md5sum -c` from the root of the restored copy rather than by
# trusting a long-gone exit code -- and it is the only record of what was
# supposed to be there if this host and its database are both gone.
MANIFEST_NAME="ktp-corpus-manifest.txt"

if [ "$COMMIT" != "1" ]; then
    echo "[corpus-offsite] DRY RUN -- no --commit, nothing will be copied"
    echo "[corpus-offsite] bundles per day-dir (10 most recent):"
    cut -d/ -f1 "$LIST" | uniq -c | tail -10 | sed 's/^/    /'
    echo "[corpus-offsite] target that WOULD be written: $RSYNC_HOSTS -> $DEST"
    echo "[corpus-offsite] manifest that WOULD ship to it: $MANIFEST_NAME (md5 + name per bundle)"
    echo "[corpus-offsite] (filenames are withheld on purpose -- they carry player names and SteamIDs)"
    exit 0
fi

{
    echo "# ktp-corpus-offsite manifest -- $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# $COUNT bundles, $(( KB / 1024 )) MB, $DAY_COUNT day-dirs, $(printf '%s\n' "$DAYS" | head -1) .. $(printf '%s\n' "$DAYS" | tail -1)"
    echo "# verify a restored copy from its root:  md5sum -c $MANIFEST_NAME"
    ( cd "$SRC" && xargs -a "$LIST" -d '\n' md5sum )
} > "$WORK/$MANIFEST_NAME" || fail "could not hash the local bundles"

# ---------------------------------------------------------------- transfer
RC=0
for H in $RSYNC_HOSTS; do
    echo "[corpus-offsite] --- $H (rsync-only target)"

    # --checksum: a bundle truncated mid-copy on an earlier run has a plausible
    # size and a fresh mtime and would otherwise be skipped forever.
    # --mkpath creates the destination, replacing the `ssh mkdir -p` this box
    # cannot serve. No --delete, deliberately: a backup that mirrors deletions
    # propagates the accident it exists to survive.
    rsync -a --checksum --mkpath --partial --human-readable -e "$RSYNC_RSH" \
          --files-from="$LIST" "$SRC/" "$H:$DEST/" \
        || { echo "[corpus-offsite] $H: rsync reported failure" >&2; RC=1; continue; }

    # Verify from the FAR SIDE by content. Any itemized FILE line is a
    # mismatch; directory lines carry 'd' in the second column and are not
    # content, so they are not failures.
    DIFFS=$(rsync -ani --checksum -e "$RSYNC_RSH" \
                  --files-from="$LIST" "$SRC/" "$H:$DEST/" 2>/dev/null \
            | grep -E '^[<>ch.*][fL]' || true)

    if [ -n "$DIFFS" ]; then
        # Count only -- an itemized line is a path, and a path here is a player.
        echo "[corpus-offsite] $H: $(printf '%s\n' "$DIFFS" | grep -c .) of $COUNT bundle(s) missing or corrupt on arrival" >&2
        RC=1
        continue
    fi

    echo "[corpus-offsite] $H: $COUNT/$COUNT verified by rsync --checksum"
    rsync -a -e "$RSYNC_RSH" "$WORK/$MANIFEST_NAME" "$H:$DEST/$MANIFEST_NAME" \
        || { echo "[corpus-offsite] $H: manifest ship failed -- the remote copy now has no durable record of what should be there" >&2; RC=1; }
done

if [ "$RC" -ne 0 ]; then
    echo "[corpus-offsite] FAILED: at least one target is incomplete" >&2
    exit 1
fi
echo "[corpus-offsite] OK: $COUNT bundle(s) verified on every target"
exit 0
