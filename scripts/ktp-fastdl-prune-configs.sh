#!/bin/bash
# Remove server-side config from the PUBLIC FastDL docroot.
#
# ktp-file-distributor treats /var/www/fastdl/dod as a distribution target alongside the 24
# game servers, and its WatchPatterns include *.cfg and *.ini -- so deploying a plugin config
# to /home/dod/distribute publishes it at https://fastdl.ktpdod.com/dod/... within seconds.
# On 2026-08-06 that tree was serving the game rcon password, the HLTV API key and the Discord
# relay secret over unauthenticated HTTP 200.
#
# The patterns cannot be dropped from the distributor: the GAME SERVERS need ac.ini and
# hltv_recorder.ini, and it has no per-target filter. So the public copy is pruned instead.
# nginx also 404s these paths -- this is the disk-layer half, so a rebuilt nginx config cannot
# re-expose them.
#
# Clients only ever fetch maps/models/sound/sprites/gfx/overviews. addons/ is server-side.
set -euo pipefail
ROOT=/var/www/fastdl/dod
n=0
if [ -d "$ROOT/addons" ]; then
    n=$(find "$ROOT/addons" -type f | wc -l)
    rm -rf "$ROOT/addons"
fi
m=$(find "$ROOT" -maxdepth 2 -name 'dodserver.cfg' -o -maxdepth 2 -name 'server.cfg' | wc -l)
find "$ROOT" -maxdepth 2 \( -name 'dodserver.cfg' -o -name 'server.cfg' \) -delete
if [ "$n" != "0" ] || [ "$m" != "0" ]; then
    echo "[$(date '+%F %T')] pruned $n addons file(s), $m server cfg(s) from the public docroot"
fi
