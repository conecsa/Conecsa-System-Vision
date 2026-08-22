"use strict";
// Mock of a Conecsa hub's Developer API for node behaviour tests (not a spec
// file — the leading underscore keeps it out of the jest testMatch glob).
//
// HTTPS with a self-signed certificate generated on first use (CA:TRUE, SAN
// 127.0.0.1 — nothing is committed to the repository), so tests exercise the
// real production path: the nodes must present the hub CA and the X-Api-Key
// header. `GET /devices` answers the device list; every `/devices/<id>/api/...`
// request is dispatched to `routes` keyed exactly like _mock-gateway
// ("METHOD /api/v1/...") after the prefix is stripped, and is recorded with the
// device id and the api key it carried.
const https = require("https");
const selfsigned = require("selfsigned");

// Mirrors a hub-issued server certificate + conecsa-hub-ca.crt: one self-signed
// CA:TRUE certificate that doubles as the CA the nodes are given, plus an
// unrelated CA to assert verification fails against it. Generated once per
// jest worker and kept in memory only.
let materialPromise = null;
function tlsMaterial() {
  if (!materialPromise) {
    const notAfter = new Date();
    notAfter.setFullYear(notAfter.getFullYear() + 1);
    const opts = (extensions) => ({ keyType: "ec", algorithm: "sha256", notAfterDate: notAfter, extensions });
    materialPromise = Promise.all([
      selfsigned.generate([{ name: "commonName", value: "hub.conecsa.local" }], opts([
        { name: "basicConstraints", cA: true, critical: true },
        { name: "subjectAltName", altNames: [
          { type: 7, ip: "127.0.0.1" },
          { type: 2, value: "localhost" },
          { type: 2, value: "hub.conecsa.local" },
        ] },
      ])),
      selfsigned.generate([{ name: "commonName", value: "other-ca.test" }], opts([
        { name: "basicConstraints", cA: true, critical: true },
      ])),
    ]).then(([hub, other]) => ({ cert: hub.cert, key: hub.private, otherCa: other.cert }));
  }
  return materialPromise;
}

const DEFAULT_DEVICES = [
  { id: "conecsa-084936", name: "Line 1", ip: "172.29.96.2", online: true, running: true, version: "2026.4", last_seen: "2026-08-22T12:00:00Z" },
  { id: "conecsa-1a2b3c", name: "Line 2", ip: "172.29.96.3", online: false, running: false, version: "2026.4", last_seen: "2026-08-21T12:00:00Z" },
];

/**
 * @param {object} [opts]
 * @param {object} [opts.routes]   "METHOD /api/..." → (req, res, body, ctx) handler
 * @param {string} [opts.apiKey]   the key the hub accepts (default "k".repeat(32))
 * @param {object[]} [opts.devices] device list returned by GET /devices
 * @param {boolean} [opts.enabled] when false every request gets 503 (API off)
 * @returns {Promise<{url, host, port, ca, apiKey, requests, close}>}
 */
async function startMockHub(opts = {}) {
  const { cert: CERT, key: KEY, otherCa: OTHER_CA } = await tlsMaterial();
  const routes = opts.routes || {};
  const apiKey = opts.apiKey || "k".repeat(32);
  const devices = opts.devices || DEFAULT_DEVICES;
  const enabled = opts.enabled !== false;
  const requests = [];
  const sseClients = [];

  const server = https.createServer({ cert: CERT, key: KEY }, (req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const fullPath = req.url.split("?")[0];
      const presented = req.headers["x-api-key"];
      requests.push({ method: req.method, path: fullPath, url: req.url, body, apiKey: presented, headers: req.headers });

      const json = (status, payload) => {
        res.writeHead(status, { "Content-Type": "application/json" });
        res.end(JSON.stringify(payload));
      };

      if (!enabled) return json(503, { error: "developer API is disabled" });
      if (!presented) return json(401, { error: "missing X-Api-Key header" });
      if (presented !== apiKey) return json(401, { error: "invalid API key" });

      if (req.method === "GET" && fullPath === "/devices") {
        return json(200, devices);
      }

      const m = fullPath.match(/^\/devices\/([^/]+)(\/api\/.*)$/);
      if (!m) return json(404, { error: "not found" });
      const deviceId = decodeURIComponent(m[1]);
      if (!devices.some((d) => d.id === deviceId)) {
        return json(404, { error: "device is not paired" });
      }
      const apiPath = m[2];
      const handler = routes[`${req.method} ${apiPath}`];
      if (handler) {
        handler(req, res, body, { deviceId });
      } else if (apiPath.endsWith("/stream")) {
        res.writeHead(200, { "Content-Type": "text/event-stream" });
        sseClients.push(res);
      } else {
        json(404, { error: "not found" });
      }
    });
  });

  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        url: `https://127.0.0.1:${port}`,
        host: "127.0.0.1",
        port,
        ca: CERT,
        otherCa: OTHER_CA,
        apiKey,
        requests,
        sseClients,
        close: () =>
          new Promise((r) => {
            sseClients.forEach((c) => c.end());
            server.closeAllConnections && server.closeAllConnections();
            server.close(r);
          }),
      });
    });
  });
}

module.exports = { startMockHub, tlsMaterial };
