#!/bin/bash
# KTP Fleet Drift Audit — weekly cron wrapper.
#
# Sources /etc/ktp/audit.env (Discord config) and invokes audit-fleet-drift.py
# against the full fleet. Writes markdown report to /var/log/ktp-audit-*.md,
# persists state to /var/lib/ktp-audit-state.json, posts NEW drift items to
# Discord via --alert-discord.
#
# Schedule: /etc/cron.d/ktp-fleet-audit runs this Monday 05:00 ET.
# Run manually for ad-hoc audits: /usr/local/bin/ktp-fleet-audit.sh

set -euo pipefail

INFRA_ROOT=/opt/ktp-infra
STATE_FILE=/var/lib/ktp-audit-state.json
REPORT="/var/log/ktp-audit-$(date +%Y%m%d-%H%M).md"

# Discord config (reuses relay URL/secret from discord-relay.conf)
[ -f /etc/ktp/audit.env ] && source /etc/ktp/audit.env
export KTP_RELAY_URL KTP_RELAY_SECRET KTP_ALERT_CHANNEL

cd "$INFRA_ROOT"
python3 scripts/audit-fleet-drift.py \
    --out "$REPORT" \
    --state "$STATE_FILE" \
    --alert-discord

echo "Report: $REPORT"