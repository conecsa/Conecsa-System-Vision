"use strict";
const http = require("http");
const { request, subscribeSSE, inferenceBaseUrl, normalizeTarget } = require("../lib/http-client");
const { startMockHub } = require("./_mock-hub");

/** Start a throwaway HTTP server on an ephemeral port; resolves with {url, close}. */
function startServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({
        url: `http://127.0.0.1:${port}`,
        close: () => new Promise((r) => server.close(r)),
      });
    });
  });
}

describe("inferenceBaseUrl", () => {
  const savedEnv = process.env.INFERENCE_URL;
  afterEach(() => {
    if (savedEnv === undefined) delete process.env.INFERENCE_URL;
    else process.env.INFERENCE_URL = savedEnv;
  });

  test("explicit per-node url wins", () => {
    process.env.INFERENCE_URL = "http://env:5000";
    expect(inferenceBaseUrl({ inferenceUrl: "http://node:9000" })).toBe(
      "http://node:9000"
    );
  });

  test("trims whitespace on explicit url", () => {
    expect(inferenceBaseUrl({ inferenceUrl: "  http://node:9000  " })).toBe(
      "http://node:9000"
    );
  });

  test("falls back to INFERENCE_URL env", () => {
    process.env.INFERENCE_URL = "http://env:5000";
    expect(inferenceBaseUrl({})).toBe("http://env:5000");
    expect(inferenceBaseUrl(null)).toBe("http://env:5000");
  });

  test("falls back to the api-gateway default", () => {
    delete process.env.INFERENCE_URL;
    expect(inferenceBaseUrl({})).toBe("http://api-gateway:5000");
    expect(inferenceBaseUrl({ inferenceUrl: "   " })).toBe(
      "http://api-gateway:5000"
    );
  });
});

describe("request", () => {
  test("GET parses the JSON response body", async () => {
    const server = await startServer((req, res) => {
      res.setHeader("Content-Type", "application/json");
      res.end(JSON.stringify({ ok: true, path: req.url }));
    });
    try {
      const body = await new Promise((resolve, reject) =>
        request(server.url, "GET", "/api/v1/status", null, (err, b) =>
          err ? reject(err) : resolve(b)
        )
      );
      expect(body).toEqual({ ok: true, path: "/api/v1/status" });
    } finally {
      await server.close();
    }
  });

  test("POST sends a JSON body with Content-Type and source header", async () => {
    let received;
    const server = await startServer((req, res) => {
      let data = "";
      req.on("data", (c) => (data += c));
      req.on("end", () => {
        received = {
          method: req.method,
          contentType: req.headers["content-type"],
          source: req.headers["x-conecsa-source"],
          body: JSON.parse(data),
        };
        res.end(JSON.stringify({ threshold: 0.6 }));
      });
    });
    try {
      const body = await new Promise((resolve, reject) =>
        request(
          server.url,
          "POST",
          "/api/v1/threshold",
          { threshold: 0.6 },
          (err, b) => (err ? reject(err) : resolve(b)),
          { source: "node-red:abc" }
        )
      );
      expect(body).toEqual({ threshold: 0.6 });
      expect(received.method).toBe("POST");
      expect(received.contentType).toBe("application/json");
      expect(received.source).toBe("node-red:abc");
      expect(received.body).toEqual({ threshold: 0.6 });
    } finally {
      await server.close();
    }
  });

  test("strips a trailing slash from the base url", async () => {
    const server = await startServer((req, res) => {
      res.end(JSON.stringify({ url: req.url }));
    });
    try {
      const body = await new Promise((resolve, reject) =>
        request(server.url + "/", "GET", "/x", null, (err, b) =>
          err ? reject(err) : resolve(b)
        )
      );
      expect(body.url).toBe("/x"); // not "//x"
    } finally {
      await server.close();
    }
  });

  test("invalid JSON yields an error", async () => {
    const server = await startServer((req, res) => res.end("not json"));
    try {
      const err = await new Promise((resolve) =>
        request(server.url, "GET", "/x", null, (e) => resolve(e))
      );
      expect(err).toBeInstanceOf(Error);
    } finally {
      await server.close();
    }
  });

  test("connection failure invokes the error callback", async () => {
    // Nothing listening on this port.
    const err = await new Promise((resolve) =>
      request("http://127.0.0.1:1", "GET", "/x", null, (e) => resolve(e))
    );
    // Node system errors can cross the jest vm realm, so assert on shape rather
    // than `instanceof Error`.
    expect(err).toBeTruthy();
    expect(typeof err.message).toBe("string");
    expect(err.code).toBeDefined(); // e.g. ECONNREFUSED
  });
});

describe("subscribeSSE", () => {
  test("parses data lines and forwards parsed JSON events", async () => {
    const server = await startServer((req, res) => {
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      res.write(": heartbeat comment\n\n");
      res.write('data: {"type":"a","n":1}\n\n');
      res.write('data: {"type":"b","n":2}\n\n');
    });
    try {
      const events = [];
      const handle = await new Promise((resolve) => {
        const h = subscribeSSE(server.url, "/stream", {
          onEvent: (ev) => {
            events.push(ev);
            if (events.length === 2) resolve(h);
          },
        });
      });
      handle.close();
      expect(events).toEqual([
        { type: "a", n: 1 },
        { type: "b", n: 2 },
      ]);
    } finally {
      await server.close();
    }
  });

  test("reports an error for a non-200 status", async () => {
    const server = await startServer((req, res) => {
      res.writeHead(500);
      res.end();
    });
    try {
      const err = await new Promise((resolve) => {
        const h = subscribeSSE(server.url, "/stream", {
          onError: (e) => {
            h.close();
            resolve(e);
          },
          reconnectMs: 50,
        });
      });
      expect(err).toBeInstanceOf(Error);
      expect(err.message).toMatch(/status 500/);
    } finally {
      await server.close();
    }
  });
});

describe("request — HTTP error statuses", () => {
  test("a non-2xx JSON reply is an error carrying the status and body", async () => {
    const server = await startServer((req, res) => {
      res.writeHead(401, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "invalid API key" }));
    });
    try {
      const err = await new Promise((resolve) =>
        request(server.url, "GET", "/devices", null, (e) => resolve(e))
      );
      expect(err).toBeInstanceOf(Error);
      expect(err.message).toBe("HTTP 401: invalid API key");
      expect(err.statusCode).toBe(401);
      expect(err.body).toEqual({ error: "invalid API key" });
    } finally {
      await server.close();
    }
  });

  test("a non-2xx non-JSON reply still reports the status", async () => {
    const server = await startServer((req, res) => {
      res.writeHead(502);
      res.end("<html>bad gateway</html>");
    });
    try {
      const err = await new Promise((resolve) =>
        request(server.url, "GET", "/x", null, (e) => resolve(e))
      );
      expect(err.message).toBe("HTTP 502");
      expect(err.statusCode).toBe(502);
    } finally {
      await server.close();
    }
  });
});

describe("normalizeTarget", () => {
  test("wraps a string base URL", () => {
    expect(normalizeTarget("http://a:1")).toEqual({ baseUrl: "http://a:1", headers: {}, tls: null });
  });
  test("keeps a target object and defaults its optional parts", () => {
    expect(normalizeTarget({ baseUrl: "https://h:8443/devices/d" })).toEqual({
      baseUrl: "https://h:8443/devices/d", headers: {}, tls: null,
    });
  });
  test("rejects anything else", () => {
    expect(() => normalizeTarget({})).toThrow(TypeError);
    expect(() => normalizeTarget(null)).toThrow(TypeError);
  });
});

describe("target objects over HTTPS (hub mode)", () => {
  let hub;
  afterEach(async () => {
    if (hub) await hub.close();
    hub = null;
  });

  function target(overrides = {}) {
    return Object.assign(
      {
        baseUrl: `${hub.url}/devices/conecsa-084936`,
        headers: { "X-Api-Key": hub.apiKey },
        tls: { ca: hub.ca, rejectUnauthorized: true },
      },
      overrides
    );
  }

  test("request sends the standing headers and trusts the hub CA", async () => {
    hub = await startMockHub({
      routes: { "GET /api/v1/status": (req, res) => res.end(JSON.stringify({ is_running: true })) },
    });
    const body = await new Promise((resolve, reject) =>
      request(target(), "GET", "/api/v1/status", null, (e, b) => (e ? reject(e) : resolve(b)), {
        source: "node-red:n1",
      })
    );
    expect(body).toEqual({ is_running: true });
    expect(hub.requests[0].path).toBe("/devices/conecsa-084936/api/v1/status");
    expect(hub.requests[0].apiKey).toBe(hub.apiKey);
    expect(hub.requests[0].headers["x-conecsa-source"]).toBe("node-red:n1");
  });

  test("verification fails against an unrelated CA or no CA", async () => {
    hub = await startMockHub();
    for (const tls of [{ ca: hub.otherCa, rejectUnauthorized: true }, { rejectUnauthorized: true }]) {
      const err = await new Promise((resolve) =>
        request(target({ tls }), "GET", "/api/v1/status", null, (e) => resolve(e))
      );
      expect(err).toBeTruthy();
      expect(err.code).toMatch(/SELF_SIGNED|UNABLE_TO_VERIFY|DEPTH_ZERO|CERT/);
    }
    expect(hub.requests).toHaveLength(0);
  });

  test("rejectUnauthorized:false connects without a CA", async () => {
    hub = await startMockHub({
      routes: { "GET /api/v1/status": (req, res) => res.end(JSON.stringify({ ok: 1 })) },
    });
    const body = await new Promise((resolve, reject) =>
      request(target({ tls: { rejectUnauthorized: false } }), "GET", "/api/v1/status", null, (e, b) =>
        e ? reject(e) : resolve(b)
      )
    );
    expect(body).toEqual({ ok: 1 });
  });

  test("a wrong key is a 401 error, not a parsed body", async () => {
    hub = await startMockHub();
    const err = await new Promise((resolve) =>
      request(target({ headers: { "X-Api-Key": "wrong-key-for-this-test" } }), "GET", "/api/v1/status", null, (e) =>
        resolve(e)
      )
    );
    expect(err.statusCode).toBe(401);
    expect(err.message).toMatch(/invalid API key/);
  });

  test("subscribeSSE carries the headers and TLS settings too", async () => {
    let sseRes;
    hub = await startMockHub({
      routes: {
        "GET /api/v1/events/stream": (req, res) => {
          res.writeHead(200, { "Content-Type": "text/event-stream" });
          sseRes = res;
          res.write('data: {"type":"state_snapshot"}\n\n');
        },
      },
    });
    const handle = await new Promise((resolve) => {
      const h = subscribeSSE(target(), "/api/v1/events/stream", {
        onEvent: (ev) => {
          expect(ev).toEqual({ type: "state_snapshot" });
          resolve(h);
        },
      });
    });
    handle.close();
    expect(sseRes).toBeDefined();
    expect(hub.requests[0].apiKey).toBe(hub.apiKey);
    expect(hub.requests[0].path).toBe("/devices/conecsa-084936/api/v1/events/stream");
  });
});
