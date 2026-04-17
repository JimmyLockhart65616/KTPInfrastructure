# KTP Game Server — Runtime Image
#
# Combines KTP build artifacts with DoD game data to produce
# a complete, runnable game server container.
#
# This mirrors the production KTP stack:
#   KTP-ReHLDS + KTPAMXX (extension mode) + DODX + ReAPI + KTPAMXXCurl
#   No Metamod. Same binaries as production bare-metal servers.
#
# Prerequisites:
#   make build                  # compile all KTP components
#   make extract-artifacts      # extract to artifacts/VERSION/
#
# Usage (via Makefile):
#   make local-build            # build this runtime image
#   make local-up               # start game server(s)
#
# Or directly:
#   docker compose -f docker-compose.local.yml build
#   docker compose -f docker-compose.local.yml up -d

# --- Stage 1: DoD game data source ---
# jives/hlds:dod provides maps, models, sounds, sprites, WADs.
# This is ONLY used as a data source — no jives binaries end up in the
# final image. KTP-ReHLDS engine replaces hlds_linux + engine_i486.so.
ARG DOD_BASE_IMAGE=jives/hlds:dod
FROM ${DOD_BASE_IMAGE} AS dod-gamedata

# --- Stage 2: Runtime ---
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# 32-bit runtime dependencies only (no build tools)
RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        lib32z1 \
        lib32stdc++6 \
        libc6-i386 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create server directory structure
RUN mkdir -p /opt/hlds/dod/addons/ktpamx/{dlls,modules,plugins,configs,data,logs}

# --- DoD game data (from jives/hlds:dod) ---
# Maps, models, sounds, sprites, WADs, valve/ shared content
COPY --from=dod-gamedata /opt/steam/hlds/dod/ /opt/hlds/dod/
COPY --from=dod-gamedata /opt/steam/hlds/valve/ /opt/hlds/valve/
COPY --from=dod-gamedata /opt/steam/hlds/libsteam_api.so /opt/hlds/libsteam_api.so

# --- KTP Build Artifacts ---
# Engine (KTP-ReHLDS — replaces stock hlds_linux + engine)
ARG VERSION=latest
COPY artifacts/${VERSION}/engine/hlds_linux /opt/hlds/hlds_linux
COPY artifacts/${VERSION}/engine/engine_i486.so /opt/hlds/engine_i486.so

# KTPAMXX platform (loaded as ReHLDS extension, no Metamod)
COPY artifacts/${VERSION}/ktpamx/dlls/ /opt/hlds/dod/addons/ktpamx/dlls/
COPY artifacts/${VERSION}/ktpamx/modules/ /opt/hlds/dod/addons/ktpamx/modules/

# KTP application plugins
COPY artifacts/${VERSION}/plugins/ /opt/hlds/dod/addons/ktpamx/plugins/

# AMXX compiler + includes (for compiling custom plugins inside the container)
COPY artifacts/${VERSION}/ktpamx/scripting/ /opt/hlds/dod/addons/ktpamx/scripting/

# extensions.ini — tells KTP-ReHLDS to load KTPAMXX as an engine extension
RUN echo 'addons/ktpamx/dlls/ktpamx_i386.so' > /opt/hlds/dod/addons/extensions.ini

# Make binaries executable
RUN chmod +x /opt/hlds/hlds_linux /opt/hlds/engine_i486.so && \
    chmod +x /opt/hlds/dod/addons/ktpamx/dlls/*.so && \
    chmod +x /opt/hlds/dod/addons/ktpamx/modules/*.so && \
    chmod +x /opt/hlds/dod/addons/ktpamx/scripting/amxxpc 2>/dev/null || true

# Entrypoint
COPY runtime/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /opt/hlds

EXPOSE 27015/udp
EXPOSE 27015/tcp
EXPOSE 26900/udp

ENTRYPOINT ["/entrypoint.sh"]
