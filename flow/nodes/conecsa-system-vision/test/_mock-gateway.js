"use strict";
// Tiny mock of the api-gateway for node behaviour tests. Not a spec file (the
// leading underscore keeps it out of the jest testMatch glob).
const http = require("http");

/**
 * Start a mock gateway. `routes` maps "METHOD /path" (query stripped) to an
 * (req, res, requestBody) handler. Unmatched requests get 404 JSON. SSE routes
 * that should stay quiet can just leave the response open.
 *
 * @returns {Promise<{url, close, requests, sseClients}>}
 */
function startMockGateway(routes = {}) {
  const requests = [];
  const sseClients = [];
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const path = req.url.split("?")[0];
      requests.push({ method: req.method, path, url: req.url, body });
      const handler = routes[`${req.method} ${path}`];
      if (handler) {
        handler(req, res, body);
      } else if (path.endsWith("/stream")) {
        // Default: open an SSE stream and hold it (no events).
        res.writeHead(200, { "Content-Type": "text/event-stream" });
        sseClients.push(res);
      } else {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "not found" }));
      }
    });
  });

  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}`,
        requests,
        sseClients,
        close: () =>
          new Promise((r) => {
            sseClients.forEach((c) => c.end());
            server.close(r);
          }),
      });
    });
  });
}

module.exports = { startMockGateway };
