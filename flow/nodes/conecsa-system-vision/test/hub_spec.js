"use strict";
const helper = require("node-red-node-test-helper");
const hubNode = require("../nodes/hub/hub.js");
const statsNode = require("../nodes/stats/stats.js");
const startStopNode = require("../nodes/start-stop/start-stop.js");
const thresholdNode = require("../nodes/threshold/threshold.js");
const { startMockHub } = require("./_mock-hub");

helper.init(require.resolve("node-red"));

const DEVICE = "conecsa-084936";

function hubFlow(hub, extra = []) {
  return [
    { id: "hub1", type: "conecsa-hub", name: "hub", host: hub.host, port: hub.port, verify: true },
    ...extra,
  ];
}

function credentials(hub, overrides = {}) {
  return { hub1: Object.assign({ apiKey: hub.apiKey, ca: hub.ca }, overrides) };
}

describe("conecsa-hub config node", () => {
  let hub;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (hub) await hub.close();
    hub = null;
  });

  it("builds the hub and device targets from its settings and credentials", async () => {
    hub = await startMockHub();
    await helper.load(hubNode, hubFlow(hub), credentials(hub));
    const n = helper.getNode("hub1");
    expect(n.type).toBe("conecsa-hub");
    expect(n.target()).toEqual({
      baseUrl: `https://127.0.0.1:${hub.port}`,
      headers: { "X-Api-Key": hub.apiKey },
      tls: { rejectUnauthorized: true, ca: hub.ca },
    });
    expect(n.target(DEVICE).baseUrl).toBe(`https://127.0.0.1:${hub.port}/devices/${DEVICE}`);
    expect(n.target("a b/c").baseUrl).toBe(`https://127.0.0.1:${hub.port}/devices/a%20b%2Fc`);
  });

  it("lists the hub's devices for the editor through the admin endpoint", async () => {
    hub = await startMockHub();
    await helper.load(hubNode, hubFlow(hub), credentials(hub));
    const res = await helper.request().get("/conecsa-hub/hub1/devices").expect(200);
    expect(res.body).toEqual([
      { id: "conecsa-084936", name: "Line 1", ip: "172.29.96.2", online: true },
      { id: "conecsa-1a2b3c", name: "Line 2", ip: "172.29.96.3", online: false },
    ]);
    expect(JSON.stringify(res.body)).not.toContain(hub.apiKey);
    expect(hub.requests[0].apiKey).toBe(hub.apiKey);
  });

  it("answers 404 not_deployed for an unknown hub id", async () => {
    hub = await startMockHub();
    await helper.load(hubNode, hubFlow(hub), credentials(hub));
    const res = await helper.request().get("/conecsa-hub/nope/devices").expect(404);
    expect(res.body.code).toBe("not_deployed");
  });

  it("passes a rejected API key through as 401", async () => {
    hub = await startMockHub();
    await helper.load(hubNode, hubFlow(hub), credentials(hub, { apiKey: "wrong-key-for-this-test" }));
    const res = await helper.request().get("/conecsa-hub/hub1/devices").expect(401);
    expect(res.body.error).toMatch(/HTTP 401/);
    expect(JSON.stringify(res.body)).not.toContain("wrong-key");
  });

  it("fails verification without the hub CA and works with verification off", async () => {
    hub = await startMockHub();
    await helper.load(hubNode, hubFlow(hub), credentials(hub, { ca: "" }));
    const res = await helper.request().get("/conecsa-hub/hub1/devices").expect(502);
    expect(res.body.code).toMatch(/SELF_SIGNED|UNABLE_TO_VERIFY|DEPTH_ZERO/);

    await helper.unload();
    const flow = hubFlow(hub);
    flow[0].verify = false;
    await helper.load(hubNode, flow, credentials(hub, { ca: "" }));
    await helper.request().get("/conecsa-hub/hub1/devices").expect(200);
  });
});

describe("nodes in hub mode", () => {
  let hub;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (hub) await hub.close();
    hub = null;
  });

  it("stats subscribes through the hub with the API key", async () => {
    let sseRes;
    hub = await startMockHub({
      routes: {
        "GET /api/v1/stats/stream": (req, res) => {
          res.writeHead(200, { "Content-Type": "text/event-stream" });
          sseRes = res;
        },
      },
    });
    const flow = hubFlow(hub, [
      { id: "n1", type: "conecsa-stats", hub: "hub1", device: DEVICE, mode: "on-change", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ]);
    await helper.load([hubNode, statsNode], flow, credentials(hub));
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");
    expect(n1.targetMode).toBe("hub");
    expect(n1.inferenceUrl).toBe(`https://127.0.0.1:${hub.port}/devices/${DEVICE}`);

    const output = new Promise((resolve) => n2.on("input", resolve));
    await new Promise((r) => setTimeout(r, 150));
    sseRes.write("data: " + JSON.stringify({ detections: 2, fps: 10, inference_time: 5, frames_with_detections: 1 }) + "\n\n");
    const msg = await output;
    expect(msg.payload.detections).toBe(2);

    const req = hub.requests.find((r) => r.path.endsWith("/stats/stream"));
    expect(req.path).toBe(`/devices/${DEVICE}/api/v1/stats/stream`);
    expect(req.apiKey).toBe(hub.apiKey);
  });

  it("start/stop posts to the device route through the hub", async () => {
    hub = await startMockHub({
      routes: {
        "GET /api/v1/status": (req, res) => res.end(JSON.stringify({ is_running: false })),
        "POST /api/v1/start": (req, res) => res.end(JSON.stringify({ success: true })),
      },
    });
    const flow = hubFlow(hub, [
      { id: "n1", type: "conecsa-start-stop", hub: "hub1", device: DEVICE, action: "start" },
    ]);
    await helper.load([hubNode, startStopNode], flow, credentials(hub));
    const n1 = helper.getNode("n1");
    n1.receive({});
    await new Promise((r) => setTimeout(r, 300));
    const post = hub.requests.find((r) => r.method === "POST");
    expect(post.path).toBe(`/devices/${DEVICE}/api/v1/start`);
    expect(post.apiKey).toBe(hub.apiKey);
    expect(post.headers["x-conecsa-source"]).toBe("node-red:n1");
  });

  it("threshold reports a 401 from the hub as a node error", async () => {
    hub = await startMockHub({
      routes: {
        "GET /api/v1/status": (req, res) => res.end(JSON.stringify({ confidence_threshold: 0.5 })),
      },
    });
    const flow = hubFlow(hub, [
      { id: "n1", type: "conecsa-threshold", hub: "hub1", device: DEVICE, wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ]);
    await helper.load([hubNode, thresholdNode], flow, credentials(hub, { apiKey: "not-the-right-key-1234" }));
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");
    let sent = false;
    n2.on("input", () => { sent = true; });
    const errored = new Promise((resolve) => n1.on("call:error", resolve));
    n1.receive({ payload: 0.7 });
    const call = await errored;
    expect(call.firstArg).toMatch(/HTTP 401/);
    expect(sent).toBe(false);
  });

  it("falls back to the direct endpoint when the hub has no device", async () => {
    hub = await startMockHub();
    const flow = hubFlow(hub, [
      { id: "n1", type: "conecsa-stats", hub: "hub1", device: "", inferenceUrl: "http://127.0.0.1:1" },
    ]);
    await helper.load([hubNode, statsNode], flow, credentials(hub));
    const n1 = helper.getNode("n1");
    expect(n1.targetMode).toBe("direct");
    expect(n1.inferenceUrl).toBe("http://127.0.0.1:1");
  });
});
