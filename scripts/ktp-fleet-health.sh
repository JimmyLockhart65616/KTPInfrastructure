#!/bin/bash
# ktp-fleet-health.sh — per-host fleet alerter, runs every minute via cron.
#
# Fires a Discord webhook alert when `pgrep -c hlds_linux` drops below the
# expected instance count for N consecutive minutes. Single alert per state
# transition (one "DEGRADED" post on decline, one "RECOVERED" post on return).
# Silent when healthy. Designed to catch any scenario that takes instances
# offline — not just the specific bug that caused the 2026-04-24 outage.
#
# DEFAULTS (overridable via ~/.ktp-fleet-health/config.sh):
#   EXPECTED=5          — 5 instances per baremetal. Chicago VPS sets 4.
#   THRESHOLD_MINUTES=3 — debounce: need 3 consecutive bad minutes before alert.
#   WEBHOOK_URL=…       — KTP Discord private / test channel.
#
# STATE (~/.ktp-fleet-health/state):
#   CONSECUTIVE_BAD=N   — minutes consecutively below expected
#   ALERT_STATE=healthy|unhealthy
#   LAST_RUN=epoch
#   LAST_RUNNING=N
#
# CRON:
#   * * * * * /home/dodserver/ktp-fleet-health.sh >/dev/null 2>&1

set -euo pipefail

HOME_DIR=${HOME:-/home/dodserver}
STATE_DIR=$HOME_DIR/.ktp-fleet-health
STATE_FILE=$STATE_DIR/state
CONFIG_FILE=$STATE_DIR/config.sh
HOSTNAME_SHORT=$(hostname -s 2>/dev/null || hostname)

mkdir -p "$STATE_DIR"

# Defaults — override via config.sh
EXPECTED=5
THRESHOLD_MINUTES=3
WEBHOOK_URL="https://discord.com/api/webhooks/1453179712862949528/0brgSCOTFzEoMnNuaCN4u1cf1COrkqpbq58XYbm-E0LzNlrCtpwt8b8iUroZVfY5nzDn"
# Discord user to @-mention on alerts. Webhooks require explicit `allowed_mentions.users`
# to actually deliver the ping — bare <@ID> in content alone gets silently stripped.
MENTION_USER_ID="218890328273321984"

# Map the raw hostname (-s) to a short location code for the alert title.
# Falls back to the raw hostname when no mapping matches.
case "$HOSTNAME_SHORT" in
    neinatl*|neinatlanta)    LOCATION="ATL" ;;
    neindallas|neindal*)     LOCATION="DAL" ;;
    neindenver|neinden*)     LOCATION="DEN" ;;
    neinnewyork|neinny*)     LOCATION="NY"  ;;
    neinchicago|neinchi*)    LOCATION="CHI" ;;
    *)                       LOCATION="$HOSTNAME_SHORT" ;;
esac

# Load per-host overrides
[ -f "$CONFIG_FILE" ] && source "$CONFIG_FILE"

# Count running instances
RUNNING=$(pgrep -c hlds_linux 2>/dev/null || echo 0)

# Load state
CONSECUTIVE_BAD=0
ALERT_STATE=healthy
[ -f "$STATE_FILE" ] && source "$STATE_FILE"

# Update consecutive-bad counter
if [ "$RUNNING" -lt "$EXPECTED" ]; then
    CONSECUTIVE_BAD=$((CONSECUTIVE_BAD + 1))
else
    CONSECUTIVE_BAD=0
fi

# Minimal JSON-escape for embed description (handles only common chars)
json_escape() {
    local s=${1//\\/\\\\}
    s=${s//\"/\\\"}
    s=${s//$'\n'/\\n}
    printf '%s' "$s"
}

send_alert() {
    local title="$1"
    local desc="$2"
    local color="$3"
    local safe_title safe_desc
    safe_title=$(json_escape "$title")
    safe_desc=$(json_escape "$desc")
    local content=""
    local allowed_mentions='"allowed_mentions":{"parse":[]}'
    if [ -n "${MENTION_USER_ID:-}" ]; then
        content="\"content\":\"<@${MENTION_USER_ID}>\","
        allowed_mentions="\"allowed_mentions\":{\"users\":[\"${MENTION_USER_ID}\"]}"
    fi
    local payload
    payload=$(printf '{%s"embeds":[{"title":"%s","description":"%s","color":%s}],%s}' \
        "$content" "$safe_title" "$safe_desc" "$color" "$allowed_mentions")
    curl -s -m 10 -X POST "$WEBHOOK_URL" \
        -H "Content-Type: application/json" \
        -d "$payload" >/dev/null 2>&1 || true
}

# Enumerate which ports look down (cosmetic, for the alert body)
down_ports() {
    local out=""
    for port in 27015 27016 27017 27018 27019; do
        [ -d "$HOME_DIR/dod-$port" ] || continue
        if ! pgrep -f "hlds_linux.*-port $port" >/dev/null 2>&1; then
            out="${out}${port} "
        fi
    done
    printf '%s' "${out% }"
}

# State transitions
if [ "$CONSECUTIVE_BAD" -ge "$THRESHOLD_MINUTES" ] && [ "$ALERT_STATE" = "healthy" ]; then
    PORTS_DOWN=$(down_ports)
    # Format the ports-down line. If enumeration returned nothing but the counter
    # says we're under expected (weird state — e.g. all processes running but count
    # mismatch from some other cause), say so explicitly instead of "unknown".
    if [ -n "$PORTS_DOWN" ]; then
        PORTS_LINE="**Missing:** ${PORTS_DOWN// /, }"
    else
        PORTS_LINE="**Missing:** (no port missing from enumeration — investigate count source mismatch)"
    fi
    send_alert \
        "🚨 ${LOCATION} DEGRADED — ${RUNNING}/${EXPECTED} hlds_linux" \
        "Below expected for **${CONSECUTIVE_BAD} min**.
${PORTS_LINE}" \
        15158332
    ALERT_STATE=unhealthy
elif [ "$RUNNING" -eq "$EXPECTED" ] && [ "$ALERT_STATE" = "unhealthy" ]; then
    send_alert \
        "✅ ${LOCATION} recovered — ${RUNNING}/${EXPECTED} hlds_linux" \
        "Back to expected instance count. Outage window: previous alert → now." \
        3066993
    ALERT_STATE=healthy
fi

# Persist state
cat > "$STATE_FILE" <<EOF
CONSECUTIVE_BAD=$CONSECUTIVE_BAD
ALERT_STATE=$ALERT_STATE
LAST_RUN=$(date +%s)
LAST_RUNNING=$RUNNING
EOF
