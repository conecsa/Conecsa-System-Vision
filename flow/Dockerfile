# Custom Node-RED image with Conecsa nodes pre-installed.
# Pinned by digest (what :latest resolved to on 2026-08-19) so a registry-side
# retag can never change what ships; bump deliberately by updating the digest.
FROM nodered/node-red@sha256:10f40d0a83e7e5852b13d4d472b2006b05b1cca6d55e2f29a55a12c25a630cb6

# Install theme collection (pinned; no floating latest)
RUN npm install --prefix /usr/src/node-red @node-red-contrib-themes/theme-collection@5.0.1

# Copy custom node package
COPY nodes/conecsa-system-vision /usr/src/node-red/node_modules/@conecsa/node-red-contrib-conecsa-system-vision

# Config + initial flow are baked into a seed dir; the entrypoint refreshes the
# config into the /data volume on every start (so settings.js changes apply on
# redeploy) while preserving user flows/credentials.
USER root
COPY settings.js theme-auto.css conecsa_white_logo.png flows.json /usr/src/node-red/conecsa-seed/
COPY conecsa-entrypoint.sh /usr/src/node-red/conecsa-entrypoint.sh
RUN chmod +x /usr/src/node-red/conecsa-entrypoint.sh \
    && chown -R node-red:node-red /data /usr/src/node-red/conecsa-seed
USER node-red

ENTRYPOINT ["/usr/src/node-red/conecsa-entrypoint.sh"]
