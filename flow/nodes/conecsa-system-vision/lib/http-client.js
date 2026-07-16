"use strict";
const http = require("http");
const https = require("https");

// Default base URL of the API gateway (the public HTTP surface). Single source
// of truth for every node; the inference-service is headless now.
const DEFAULT_INFERENCE_URL = "http://api-gateway:5000";

/**
 * Resolve the API base URL for a node.
 *
 * Precedence: an explicit per-node `inferenceUrl` (from the editor) → the
 * `INFERENCE_URL` environment variable → the api-gateway default. This lets the
 * whole deployment be repointed with one env var instead of editing every node.
 *
 * @param {object} config - the node config (may carry `inferenceUrl`)
 * @returns {string} base URL, e.g. "http://api-gateway:5000"
 */
function inferenceBaseUrl(config) {
  const explicit = config && config.inferenceUrl && String(config.inferenceUrl).trim();
  return explicit || process.env.INFERENCE_URL || DEFAULT_INFERENCE_URL;
}

/**
 * Perform an HTTP/HTTPS JSON request.
 *
 * @param {string} baseUrl  - e.g. "http://api-gateway:5000"
 * @param {string} method   - HTTP verb
 * @param {string} path     - e.g. "/api/v1/stats"
 * @param {object|null} body - JSON body (for POST/PUT) or null
 * @param {function} cb     - callback(err, parsedBody)
 */
function request(baseUrl, method, path, body, cb, opts = {}) {
  const cleanBase = baseUrl.replace(/\/$/, "");
  const fullUrl = cleanBase + path;
  const mod = fullUrl.startsWith("https") ? https : http;

  const requestOptions = { method };

  const headers = Object.assign({}, opts.headers || {});
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  if (opts.source) {
    headers["X-Conecsa-Source"] = opts.source;
  }
  if (Object.keys(headers).length > 0) {
    requestOptions.headers = headers;
  }

  const req = mod.request(fullUrl, requestOptions, (res) => {
    let data = "";
    res.on("data", (chunk) => (data += chunk));
    res.on("end", () => {
      try {
        cb(null, JSON.parse(data));
      } catch (e) {
        cb(e);
      }
    });
  });
  req.on("error", cb);

  if (body) {
    req.write(JSON.stringify(body));
  }
  req.end();
}

/**
 * Subscribe to a Server-Sent Events endpoint and forward each parsed
 * JSON `data:` payload through `onEvent`. Built on Node's stdlib `http`
 * module — no external dependency.
 *
 * The connection auto-reconnects with a fixed backoff on error or
 * server-side close. Heartbeat comment lines (lines starting with `:`)
 * are ignored.
 *
 * @param {string}   baseUrl  - e.g. "http://api-gateway:5000"
 * @param {string}   path     - e.g. "/api/v1/stats/stream"
 * @param {object}   handlers
 * @param {function} handlers.onEvent       - (parsedJson) => void
 * @param {function} [handlers.onError]     - (err) => void
 * @param {number}   [handlers.reconnectMs] - default 3000
 * @returns {{ close: () => void }} handle whose `close()` aborts the stream
 */
function subscribeSSE(baseUrl, path, { onEvent, onError, reconnectMs = 3000 } = {}) {
  const cleanBase = baseUrl.replace(/\/$/, "");
  const fullUrl = cleanBase + path;
  const mod = fullUrl.startsWith("https") ? https : http;

  let req = null;
  let closed = false;
  let reconnectTimer = null;

  function scheduleReconnect() {
    if (closed || reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (!closed) connect();
    }, reconnectMs);
  }

  function connect() {
    req = mod.get(
      fullUrl,
      { headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" } },
      (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          if (onError) onError(new Error(`SSE returned status ${res.statusCode}`));
          return scheduleReconnect();
        }
        res.setEncoding("utf8");
        let buffer = "";
        res.on("data", (chunk) => {
          buffer += chunk;
          // SSE events are delimited by a blank line ("\n\n" or "\r\n\r\n").
          while (true) {
            const lfIdx = buffer.indexOf("\n\n");
            const crlfIdx = buffer.indexOf("\r\n\r\n");
            let idx;
            let delimLen;
            if (lfIdx >= 0 && (crlfIdx === -1 || lfIdx < crlfIdx)) {
              idx = lfIdx;
              delimLen = 2;
            } else if (crlfIdx >= 0) {
              idx = crlfIdx;
              delimLen = 4;
            } else {
              break;
            }

            const event = buffer.slice(0, idx);
            buffer = buffer.slice(idx + delimLen);
            const dataLines = [];
            for (const line of event.split(/\r?\n/)) {
              if (line.startsWith("data:")) {
                dataLines.push(line.slice(5).replace(/^ /, ""));
              }
              // Comment (":..."), `event:`, `id:` and `retry:` are ignored.
            }
            if (dataLines.length === 0) continue;
            try {
              onEvent(JSON.parse(dataLines.join("\n")));
            } catch (e) {
              if (onError) onError(e);
            }
          }
        });
        res.on("end", scheduleReconnect);
        res.on("error", (e) => {
          if (onError) onError(e);
          scheduleReconnect();
        });
      },
    );
    req.on("error", (e) => {
      if (onError) onError(e);
      scheduleReconnect();
    });
  }

  connect();

  return {
    close() {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (req) {
        req.destroy();
        req = null;
      }
    },
  };
}

module.exports = { request, subscribeSSE, inferenceBaseUrl };
