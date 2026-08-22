/**
 * @file conecsa-hub config node — how the other nodes reach devices through a
 *   Conecsa hub's Developer API (`https://<hub>:<port>/devices/<id>/api/...`,
 *   `X-Api-Key` header, TLS signed by the hub's own CA). One hub config is
 *   shared by every node that selects it; the API key and the CA certificate
 *   are credentials (encrypted in flows_cred.json, never exported with a flow).
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { request } = require("../../lib/http-client");

  const DEFAULT_PORT = 8443;

  function HubNode(n) {
    RED.nodes.createNode(this, n);
    this.host = String(n.host || "").trim();
    this.port = parseInt(n.port, 10) || DEFAULT_PORT;
    this.verify = n.verify !== false;
    const creds = this.credentials || {};
    this.apiKey = creds.apiKey || "";
    this.ca = creds.ca || "";

    if (!this.host) this.warn("hub host is not set");
    if (!this.apiKey) this.warn("hub API key is not set");
    if (this.verify && !this.ca) {
      this.warn(
        "certificate verification is on but no CA certificate is loaded — " +
          "upload the hub's CA (Settings → Developer) or turn verification off",
      );
    }
  }

  /**
   * Request target for the hub itself (`deviceId` omitted) or for one device
   * through it. Nodes hand this to `request`/`subscribeSSE` unchanged.
   *
   * @param {string} [deviceId] device id as listed by the hub
   * @returns {{ baseUrl: string, headers: object, tls: object }}
   */
  HubNode.prototype.target = function (deviceId) {
    let baseUrl = `https://${this.host}:${this.port}`;
    if (deviceId) {
      baseUrl += `/devices/${encodeURIComponent(deviceId)}`;
    }
    const tls = { rejectUnauthorized: this.verify };
    if (this.ca) tls.ca = this.ca;
    return {
      baseUrl,
      headers: this.apiKey ? { "X-Api-Key": this.apiKey } : {},
      tls,
    };
  };

  RED.nodes.registerType("conecsa-hub", HubNode, {
    credentials: {
      apiKey: { type: "password" },
      ca: { type: "text" },
    },
  });

  // Editor helper: the Device select in every node asks a *deployed* hub config
  // for its paired devices. Relative to httpAdminRoot, like core nodes
  // (`inject/:id`). The API key never leaves the runtime.
  RED.httpAdmin.get(
    "/conecsa-hub/:id/devices",
    RED.auth.needsPermission("conecsa-hub.read"),
    function (req, res) {
      const hub = RED.nodes.getNode(req.params.id);
      if (!hub || hub.type !== "conecsa-hub") {
        return res
          .status(404)
          .json({ error: "hub configuration not deployed", code: "not_deployed" });
      }
      request(hub.target(), "GET", "/devices", null, (err, body) => {
        if (err) {
          const status =
            err.statusCode === 401 || err.statusCode === 503 ? err.statusCode : 502;
          return res.status(status).json({ error: err.message, code: err.code || "" });
        }
        const devices = Array.isArray(body) ? body : [];
        res.json(
          devices.map((d) => ({
            id: d.id,
            name: d.name,
            ip: d.ip,
            online: !!d.online,
          })),
        );
      });
    },
  );
};
