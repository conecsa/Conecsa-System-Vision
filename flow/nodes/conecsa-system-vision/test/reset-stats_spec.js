"use strict";
const helper = require("node-red-node-test-helper");
const resetStatsNode = require("../nodes/reset-stats/reset-stats.js");
const { startMockGateway } = require("./_mock-gateway");

helper.init(require.resolve("node-red"));

const okRoutes = {
  "POST /api/v1/counter/reset": (req, res) => res.end(JSON.stringify({ success: true })),
  "POST /api/v1/stats/reset": (req, res) => res.end(JSON.stringify({ success: true })),
};

describe("reset-stats node", () => {
  let gw;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (gw) await gw.close();
    gw = null;
  });

  it("registers with its configured type and default scope", async () => {
    gw = await startMockGateway(okRoutes);
    const flow = [{ id: "n1", type: "reset-stats", inferenceUrl: gw.url }];
    await helper.load(resetStatsNode, flow);
    const n1 = helper.getNode("n1");
    expect(n1).toBeDefined();
    expect(n1.type).toBe("reset-stats");
    expect(n1.scope).toBe("all");
  });

  it("scope counter resets only the counter", async () => {
    gw = await startMockGateway(okRoutes);
    const flow = [
      { id: "n1", type: "reset-stats", inferenceUrl: gw.url, scope: "counter", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(resetStatsNode, flow);
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({});
    const msg = await output;

    expect(msg.payload).toEqual({ reset: "counter", success: true });
    const paths = gw.requests.filter((r) => r.method === "POST").map((r) => r.path);
    expect(paths).toEqual(["/api/v1/counter/reset"]);
  });

  it("scope all resets the counter first, then the stats", async () => {
    gw = await startMockGateway(okRoutes);
    const flow = [
      { id: "n1", type: "reset-stats", inferenceUrl: gw.url, scope: "all", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(resetStatsNode, flow);
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({});
    const msg = await output;

    expect(msg.payload).toEqual({ reset: "all", success: true });
    const paths = gw.requests.filter((r) => r.method === "POST").map((r) => r.path);
    expect(paths).toEqual(["/api/v1/counter/reset", "/api/v1/stats/reset"]);
  });

  it("msg.scope overrides the configured scope", async () => {
    gw = await startMockGateway(okRoutes);
    const flow = [
      { id: "n1", type: "reset-stats", inferenceUrl: gw.url, scope: "counter", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(resetStatsNode, flow);
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({ scope: "stats" });
    const msg = await output;

    expect(msg.payload).toEqual({ reset: "stats", success: true });
    const paths = gw.requests.filter((r) => r.method === "POST").map((r) => r.path);
    expect(paths).toEqual(["/api/v1/stats/reset"]);
  });

  it("reports an error and sends nothing when the gateway fails", async () => {
    // A connection reset (not an HTTP error status: request() surfaces only
    // transport errors) drives the error path.
    gw = await startMockGateway({
      "POST /api/v1/counter/reset": (req, res) => res.socket.destroy(),
    });
    const flow = [
      { id: "n1", type: "reset-stats", inferenceUrl: gw.url, scope: "counter", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(resetStatsNode, flow);
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");

    let sent = false;
    n2.on("input", () => { sent = true; });
    const errored = new Promise((resolve) => n1.on("call:error", resolve));
    n1.receive({});
    await errored;

    expect(sent).toBe(false);
  });
});
