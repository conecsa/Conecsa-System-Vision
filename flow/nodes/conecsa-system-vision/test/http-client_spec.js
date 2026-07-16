"use strict";
const http = require("http");
const { request, subscribeSSE, inferenceBaseUrl } = require("../lib/http-client");

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
