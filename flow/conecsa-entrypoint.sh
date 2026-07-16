#!/bin/sh
# Node-RED keeps its config (settings.js, theme, logo) and user data (flows,
# credentials) in the same /data volume. A named volume is populated only once,
# so image updates to settings.js would otherwise never reach an existing
# deployment. Refresh the image-owned CONFIG files into /data on every start
# (so redeploys apply), while leaving user flows/credentials untouched.
set -e

SEED=/usr/src/node-red/conecsa-seed

for f in settings.js theme-auto.css conecsa_white_logo.png; do
    if [ -f "$SEED/$f" ]; then
        cp -f "$SEED/$f" "/data/$f"
    fi
done

# Seed/refresh the default flow. A named volume persists across redeploys, so a
# plain "copy only when absent" guard means a stale or empty flows.json left in
# the volume permanently shadows the image's default — the default never loads on
# `compose up -d --build`. Track the last-seeded default in a marker file and
# refresh the on-disk flow whenever it still matches that marker (i.e. the user
# hasn't edited it via the UI); a user-edited flow differs from the marker and is
# left untouched.
#
# Bootstrap: a device deployed with the old "copy only if absent" entrypoint has
# a flows.json but no marker. We can't tell from bytes alone whether that file is
# a stale default or a field edit, so we treat a missing marker as "unedited" and
# refresh from the image (one-time). This guarantees the shipped default loads on
# the migration deploy; from then on the marker exists and protects UI edits.
SEED_MARKER=/data/.conecsa-flows.seed
if [ -f "$SEED/flows.json" ]; then
    if [ ! -f /data/flows.json ] \
        || [ ! -f "$SEED_MARKER" ] \
        || cmp -s /data/flows.json "$SEED_MARKER"; then
        cp "$SEED/flows.json" /data/flows.json
        cp "$SEED/flows.json" "$SEED_MARKER"
    fi
fi

exec /usr/src/node-red/entrypoint.sh "$@"
