"use strict";
const helper = require("node-red-node-test-helper");
const triggerNode = require("../nodes/trigger/trigger.js");
const { startMockGateway } = require("./_mock-gateway");

helper.init(require.resolve("node-red"));

function routes(triggerEnabled) {
  return {
    "GET /api/v1/trigger/status": (req, res) =>
      res.end(JSON.stringify({ trigger_enabled: triggerEnabled })),
    "POST /api/v1/trigger/enable": (req, res) =>
      res.end(JSON.stringify({ trigger_enabled: true })),
    "POST /api/v1/trigger/disable": (req, res) =>
      res.end(JSON.stringify({ trigger_enabled: false })),
  };
}

async function loadTrigger(gw, nodeConfig) {
  const flow = [
    { id: "n1", type: "camera-trigger", inferenceUrl: gw.url, wires: [["n2"]], ...nodeConfig },
    { id: "n2", type: "helper" },
  ];
  await helper.load(triggerNode, flow);
  return { n1: helper.getNode("n1"), n2: helper.getNode("n2") };
}

function postedPaths(gw) {
  return gw.requests.filter((r) => r.method === "POST").map((r) => r.path);
}

describe("camera-trigger node", () => {
  let gw;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (gw) await gw.close();
    gw = null;
  });

  it("registers with its configured type and default action", async () => {
    gw = await startMockGateway(routes(false));
    const { n1 } = await loadTrigger(gw, {});
    expect(n1).toBeDefined();
    expect(n1.type).toBe("camera-trigger");
    expect(n1.action).toBe("toggle");
  });

  it("enable posts to the enable endpoint and emits the response", async () => {
    gw = await startMockGateway(routes(false));
    const { n1, n2 } = await loadTrigger(gw, { action: "enable" });

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({});
    const msg = await output;

    expect(msg.payload).toEqual({ trigger_enabled: true });
    expect(postedPaths(gw)).toEqual(["/api/v1/trigger/enable"]);
  });

  it("toggle inverts the current trigger status", async () => {
    gw = await startMockGateway(routes(true));
    const { n1, n2 } = await loadTrigger(gw, { action: "toggle" });

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({});
    const msg = await output;

    expect(msg.payload).toEqual({ trigger_enabled: false });
    expect(postedPaths(gw)).toEqual(["/api/v1/trigger/disable"]);
  });

  it("action payload maps a boolean payload to enable/disable", async () => {
    gw = await startMockGateway(routes(false));
    const { n1, n2 } = await loadTrigger(gw, { action: "payload" });

    let output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({ payload: true });
    await output;

    output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({ payload: false });
    await output;

    expect(postedPaths(gw)).toEqual([
      "/api/v1/trigger/enable",
      "/api/v1/trigger/disable",
    ]);
  });

  it("msg.action overrides the configured action", async () => {
    gw = await startMockGateway(routes(true));
    const { n1, n2 } = await loadTrigger(gw, { action: "enable" });

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({ action: "disable" });
    await output;

    expect(postedPaths(gw)).toEqual(["/api/v1/trigger/disable"]);
  });

  it("a non-toggle action still applies when the status fetch fails", async () => {
    // The status GET dies with a connection reset; enable proceeds regardless.
    gw = await startMockGateway({
      "GET /api/v1/trigger/status": (req, res) => res.socket.destroy(),
      "POST /api/v1/trigger/enable": (req, res) =>
        res.end(JSON.stringify({ trigger_enabled: true })),
    });
    const { n1, n2 } = await loadTrigger(gw, { action: "enable" });

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({});
    const msg = await output;

    expect(msg.payload).toEqual({ trigger_enabled: true });
  });

  it("toggle errors out when the status is unreachable", async () => {
    // request() surfaces only transport errors, so reset the connection.
    gw = await startMockGateway({
      "GET /api/v1/trigger/status": (req, res) => res.socket.destroy(),
    });
    const { n1, n2 } = await loadTrigger(gw, { action: "toggle" });

    let sent = false;
    n2.on("input", () => { sent = true; });
    const errored = new Promise((resolve) => n1.on("call:error", resolve));
    n1.receive({});
    await errored;

    expect(sent).toBe(false);
    expect(postedPaths(gw)).toEqual([]);
  });
});
