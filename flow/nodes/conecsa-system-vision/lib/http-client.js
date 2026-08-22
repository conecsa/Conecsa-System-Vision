"use strict";
const http = require("http");
const https = require("https");

// Default base URL of the API gateway (the public HTTP surface). Single source
// of truth for every node; the inference-service is headless now.
const DEFAULT_INFERENCE_URL = "http://api-gateway:5000";

/**
 * Resolve the direct API base URL for a node (no hub involved).
 *
 * Precedence: an explicit per-node `inferenceUrl` (the "API endpoint" field in
 * the editor) → the `INFERENCE_URL` environment variable → the api-gateway
 * default. This lets the whole on-device deployment be repointed with one env
 * var instead of editing every node.
 *
 * @param {object} config - the node config (may carry `inferenceUrl`)
 * @returns {string} base URL, e.g. "http://api-gateway:5000"
 */
function inferenceBaseUrl(config) {
  const explicit = config && config.inferenceUrl && String(config.inferenceUrl).trim();
  return explicit || process.env.INFERENCE_URL || DEFAULT_INFERENCE_URL;
}

/**
 * A request target is either a plain base URL string (direct mode) or an
 * object describing how to reach the API through a hub:
 *
 *   { baseUrl: "https://hub:8443/devices/<id>",
 *     headers: { "X-Api-Key": "..." },          // merged into every request
 *     tls:     { ca: "<PEM>", rejectUnauthorized: true } }
 *
 * @param {string|object} target
 * @returns {{ baseUrl: string, headers: object, tls: object|null }}
 */
function normalizeTarget(target) {
  if (typeof target === "string") {
    return { baseUrl: target, headers: {}, tls: null };
  }
  if (!target || typeof target.baseUrl !== "string") {
    throw new TypeError(
      "http-client: target must be a base URL string or { baseUrl, headers, tls }",
    );
  }
  return {
    baseUrl: target.baseUrl,
    headers: target.headers || {},
    tls: target.tls || null,
  };
}

/**
 * Build the `{ fullUrl, mod, options }` triple shared by `request` and
 * `subscribeSSE`: joins the path onto the base URL, picks http/https, merges
 * the target's standing headers with the per-call ones and, for HTTPS, copies
 * the target's TLS settings (`ca`, `rejectUnauthorized`, `servername`) into
 * the request options — Node passes them straight through to `tls.connect`.
 */
function buildRequest(target, path, extraHeaders) {
  const t = normalizeTarget(target);
  const fullUrl = t.baseUrl.replace(/\/$/, "") + path;
  const isHttps = fullUrl.startsWith("https");
  const options = { headers: Object.assign({}, t.headers, extraHeaders || {}) };
  if (isHttps && t.tls) {
    if (t.tls.ca) options.ca = t.tls.ca;
    if (typeof t.tls.rejectUnauthorized === "boolean") {
      options.rejectUnauthorized = t.tls.rejectUnauthorized;
    }
    if (t.tls.servername) options.servername = t.tls.servername;
  }
  return { fullUrl, mod: isHttps ? https : http, options };
}

/**
 * Perform an HTTP/HTTPS JSON request.
 *
 * A non-2xx status is reported as an error (`err.statusCode`, `err.body`) —
 * a hub answering 401 for a bad API key, or 503 while its Developer API is
 * off, must not be mistaken for a successful reply.
 *
 * @param {string|object} target - base URL or target object (see normalizeTarget)
 * @param {string} method   - HTTP verb
 * @param {string} path     - e.g. "/api/v1/stats"
 * @param {object|null} body - JSON body (for POST/PUT) or null
 * @param {function} cb     - callback(err, parsedBody)
 */
function request(target, method, path, body, cb, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  if (opts.source) {
    headers["X-Conecsa-Source"] = opts.source;
  }

  const { fullUrl, mod, options } = buildRequest(target, path, headers);
  options.method = method;
  if (Object.keys(options.headers).length === 0) {
    delete options.headers;
  }

  const req = mod.request(fullUrl, options, (res) => {
    let data = "";
    res.on("data", (chunk) => (data += chunk));
    res.on("end", () => {
      let parsed;
      try {
        parsed = JSON.parse(data);
      } catch (e) {
        if (res.statusCode >= 400) {
          // An error status with a non-JSON body (nginx page, empty reply):
          // report the status rather than the parse failure.
          return cb(httpError(res.statusCode, null));
        }
        return cb(e);
      }
      if (res.statusCode >= 400) {
        return cb(httpError(res.statusCode, parsed));
      }
      cb(null, parsed);
    });
  });
  req.on("error", cb);

  if (body) {
    req.write(JSON.stringify(body));
  }
  req.end();
}

function httpError(statusCode, parsed) {
  const detail = parsed && typeof parsed.error === "string" ? `: ${parsed.error}` : "";
  const err = new Error(`HTTP ${statusCode}${detail}`);
  err.statusCode = statusCode;
  err.body = parsed;
  return err;
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
 * @param {string|object} target - base URL or target object (see normalizeTarget)
 * @param {string}   path     - e.g. "/api/v1/stats/stream"
 * @param {object}   handlers
 * @param {function} handlers.onEvent       - (parsedJson) => void
 * @param {function} [handlers.onError]     - (err) => void
 * @param {number}   [handlers.reconnectMs] - default 3000
 * @returns {{ close: () => void }} handle whose `close()` aborts the stream
 */
function subscribeSSE(target, path, { onEvent, onError, reconnectMs = 3000 } = {}) {
  const { fullUrl, mod, options } = buildRequest(target, path, {
    Accept: "text/event-stream",
    "Cache-Control": "no-cache",
  });

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
    req = mod.get(fullUrl, options, (res) => {
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
    });
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

module.exports = { request, subscribeSSE, inferenceBaseUrl, normalizeTarget };
