#!/usr/bin/env bash
# deploy-lan-web — push sites/lan-web/app to /opt/lan-web/app, deliberately.
#
# /opt/lan-web was hand-managed from June to August 2026: no deploy script, no
# drift check, 19 .deploy-bak-* directories (85 MB) as the fossil record. Two
# things went wrong in that window and both are the reason this script exists:
# the box ran a bracket.py whose fix had been on main for five days, and a
# warmup panel lived only on the box where the first rsync would have deleted
# it.
#
# So this is a deliberate deploy with a pre-flight, matching the house pattern
# (stage-wave.py, deploy-to-fleet.py, the .new + nightly-swap path) rather than
# a git pull that changes live code the moment someone commits.
#
#   ./deploy-lan-web.sh              # dry run, shows what would change
#   ./deploy-lan-web.sh --apply      # do it
#
# Needs rsync, ssh and python3, so run it from WSL or the data server — not
# from Git Bash on Windows, which has none of the three.
#
# Refuses to run if the drift check reports BOX-ONLY files: --delete would
# destroy them, and "it was only on the server" is exactly how the warmup panel
# nearly went. Commit them first, or pass --force-delete-box-only if you mean it.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/sites/lan-web/app/"
HOST="${DATA_SSH_HOST:-74.91.112.242}"
USER="${DATA_SSH_USER:-root}"
DST="/opt/lan-web/app/"
UNIT="lan-web"
STAMP="$(date +%Y%m%d-%H%M%S)"

APPLY=0
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --apply)                  APPLY=1 ;;
    --force-delete-box-only)  FORCE=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

[ -d "$SRC" ] || { echo "source tree missing: $SRC" >&2; exit 2; }

echo "== pre-flight: drift check =="
set +e
DRIFT="$(python3 "$REPO_ROOT/scripts/ktp-lan-web-drift.py" 2>&1)"; DRIFT_RC=$?
set -e
echo "$DRIFT"
# Only 0 and 1 are answers. Anything else -- 2 from the checker, 127 from a
# missing python3, a traceback -- means we did not learn whether the box has
# box-only files, and proceeding would --delete on the strength of a question
# that was never asked.
if [ "$DRIFT_RC" -ne 0 ] && [ "$DRIFT_RC" -ne 1 ]; then
  echo >&2
  echo "drift check did not run (exit $DRIFT_RC) — refusing to deploy blind." >&2
  exit 2
fi
if echo "$DRIFT" | grep -q '^BOX-ONLY' && [ "$FORCE" -ne 1 ]; then
  echo >&2
  echo "REFUSING: files exist only on the box and --delete would destroy them." >&2
  echo "Commit them, or re-run with --force-delete-box-only." >&2
  exit 1
fi

# venv/ and migrations state live inside the target and are NOT ours to manage;
# .deploy-bak-* are the old hand-deploy fossils and sit above app/ anyway.
RSYNC_ARGS=(-rlpt --delete --itemize-changes
            --exclude 'venv/' --exclude '__pycache__/' --exclude '*.pyc'
            --exclude '.deploy-bak-*/')

if [ "$APPLY" -ne 1 ]; then
  echo
  echo "== DRY RUN — what would change =="
  rsync "${RSYNC_ARGS[@]}" --dry-run "$SRC" "$USER@$HOST:$DST"
  echo
  echo "(nothing was changed; re-run with --apply)"
  exit 0
fi

echo
echo "== backup (a tarball, not another .deploy-bak- directory) =="
ssh "$USER@$HOST" "tar czf /root/lan-web-app-$STAMP.tgz -C /opt/lan-web app \
  && ls -l /root/lan-web-app-$STAMP.tgz"

echo
echo "== deploy =="
rsync "${RSYNC_ARGS[@]}" "$SRC" "$USER@$HOST:$DST"
ssh "$USER@$HOST" "chown -R lanweb:lanweb /opt/lan-web/app && \
  find /opt/lan-web/app -type f -exec chmod 644 {} + && \
  find /opt/lan-web/app -type d -exec chmod 755 {} +"

echo
echo "== restart =="
ssh "$USER@$HOST" "systemctl restart $UNIT && sleep 3 && systemctl is-active $UNIT"

echo
echo "== verify: serving, and in sync =="
ssh "$USER@$HOST" "curl -sS -o /dev/null -w 'lan-web http %{http_code}\n' http://127.0.0.1:8099/"
python3 "$REPO_ROOT/scripts/ktp-lan-web-drift.py"
