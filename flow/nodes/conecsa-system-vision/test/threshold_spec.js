"use strict";
const helper = require("node-red-node-test-helper");
const thresholdNode = require("../nodes/threshold/threshold.js");
const { startMockGateway } = require("./_mock-gateway");

helper.init(require.resolve("node-red"));

describe("threshold node", () => {
  let gw;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (gw) await gw.close();
    gw = null;
  });

  it("registers with its configured type and defaults", async () => {
    gw = await startMockGateway({
      "GET /api/v1/status": (req, res) =>
        res.end(JSON.stringify({ confidence_threshold: 0.5, overlay_threshold: 0.4 })),
    });
    const flow = [{ id: "n1", type: "threshold", inferenceUrl: gw.url }];
    await helper.load(thresholdNode, flow);
    const n1 = helper.getNode("n1");
    expect(n1).toBeDefined();
    expect(n1.type).toBe("threshold");
    expect(n1.thresholdType).toBe("confidence");
    expect(n1.value).toBe(0.5);
  });

  it("posts the threshold on input and emits the response", async () => {
    gw = await startMockGateway({
      "GET /api/v1/status": (req, res) =>
        res.end(JSON.stringify({ confidence_threshold: 0.5, overlay_threshold: 0.4 })),
      "POST /api/v1/threshold": (req, res, body) => {
        const b = JSON.parse(body);
        res.end(JSON.stringify({ threshold: b.threshold }));
      },
    });
    const flow = [
      { id: "n1", type: "threshold", inferenceUrl: gw.url, thresholdType: "confidence", value: 0.5, wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(thresholdNode, flow);
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({ payload: 0.7 });
    const msg = await output;

    expect(msg.payload).toEqual({ threshold: 0.7 });
    const post = gw.requests.find(
      (r) => r.method === "POST" && r.path === "/api/v1/threshold"
    );
    expect(JSON.parse(post.body)).toEqual({ threshold: 0.7 });
  });

  it("routes overlay threshold to the overlay endpoint", async () => {
    gw = await startMockGateway({
      "GET /api/v1/status": (req, res) =>
        res.end(JSON.stringify({ confidence_threshold: 0.5, overlay_threshold: 0.4 })),
      "POST /api/v1/overlay_threshold": (req, res, body) =>
        res.end(JSON.stringify({ threshold: JSON.parse(body).threshold })),
    });
    const flow = [
      { id: "n1", type: "threshold", inferenceUrl: gw.url, thresholdType: "overlay", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(thresholdNode, flow);
    const n1 = helper.getNode("n1");
    const n2 = helper.getNode("n2");

    const output = new Promise((resolve) => n2.on("input", resolve));
    n1.receive({ payload: 0.33 });
    await output;

    expect(
      gw.requests.some((r) => r.method === "POST" && r.path === "/api/v1/overlay_threshold")
    ).toBe(true);
  });
});
