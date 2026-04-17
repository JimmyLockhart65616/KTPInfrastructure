#!/bin/bash
# KTP Game Server Entrypoint
#
# 1. Copies config files from /config/ mount into KTPAMXX config paths
# 2. Copies additional plugins from /plugins/ mount
# 3. Launches hlds_linux with KTP-ReHLDS
#
# Environment variables:
#   MAP           - Starting map (default: dod_anzio)
#   MAXPLAYERS    - Max player slots (default: 14)
#   RCON_PASSWORD - RCON password (default: changeme)

set -e

HLDS_DIR=/opt/hlds
DOD_DIR=$HLDS_DIR/dod
KTPAMX_DIR=$DOD_DIR/addons/ktpamx

# --- Config files ---
# If /config/ is mounted, copy config files into place.
# This lets docker-compose mount a config profile (lan/, local/, online/)
# and have it applied at startup without baking configs into the image.
if [ -d /config ]; then
    for f in modules.ini plugins.ini discord.ini hltv_recorder.ini; do
        if [ -f "/config/$f" ]; then
            cp "/config/$f" "$KTPAMX_DIR/configs/$f"
            echo "[entrypoint] Installed config: $f"
        fi
    done

    if [ -f /config/dodserver.cfg ]; then
        cp /config/dodserver.cfg "$DOD_DIR/dodserver.cfg"
        echo "[entrypoint] Installed dodserver.cfg"
    fi
fi

# --- Additional plugins ---
# Mount a directory of .amxx files at /plugins/ to add plugins
# beyond the standard KTP set (e.g., HUD Observer plugin during dev).
if [ -d /plugins ] && ls /plugins/*.amxx >/dev/null 2>&1; then
    cp /plugins/*.amxx "$KTPAMX_DIR/plugins/"
    echo "[entrypoint] Installed additional plugins:"
    ls /plugins/*.amxx | xargs -n1 basename | sed 's/^/  /'
fi

# --- Launch ---
export LD_LIBRARY_PATH="$HLDS_DIR:${LD_LIBRARY_PATH:-}"

MAP="${MAP:-dod_anzio}"
MAXPLAYERS="${MAXPLAYERS:-14}"
RCON_PASSWORD="${RCON_PASSWORD:-changeme}"

echo "[entrypoint] KTP-ReHLDS starting: map=$MAP maxplayers=$MAXPLAYERS"
echo "[entrypoint] Extensions:"
cat "$DOD_DIR/addons/extensions.ini" | sed 's/^/  /'
echo "[entrypoint] Plugins:"
cat "$KTPAMX_DIR/configs/plugins.ini" 2>/dev/null | grep -v '^;' | grep -v '^$' | sed 's/^/  /' || echo "  (no plugins.ini)"

exec "$HLDS_DIR/hlds_linux" -game dod \
    +log on \
    +rcon_password "$RCON_PASSWORD" \
    +maxplayers "$MAXPLAYERS" \
    +map "$MAP" \
    "$@"
