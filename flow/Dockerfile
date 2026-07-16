# Custom Node-RED image with Conecsa nodes pre-installed
FROM nodered/node-red:latest

# Install theme collection
RUN npm install --prefix /usr/src/node-red @node-red-contrib-themes/theme-collection

# Copy custom node package
COPY nodes/conecsa-system-vision /usr/src/node-red/node_modules/node-red-contrib-conecsa-system-vision

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
