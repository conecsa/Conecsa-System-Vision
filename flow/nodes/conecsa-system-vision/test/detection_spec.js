"use strict";
const helper = require("node-red-node-test-helper");
const detectionNode = require("../nodes/detection/detection.js");
const { startMockGateway } = require("./_mock-gateway");

helper.init(require.resolve("node-red"));

describe("detection node", () => {
  let gw;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (gw) await gw.close();
    gw = null;
  });

  it("emits the snapshot payload when there are detections", async () => {
    gw = await startMockGateway({
      "GET /api/v1/detections/snapshot": (req, res) =>
        res.end(
          JSON.stringify({
            total: 1,
            model: "yolo",
            detections: [{ class_name: "cap", area: { label: "zone-1" } }],
          })
        ),
    });
    const flow = [
      { id: "n1", type: "detection", inferenceUrl: gw.url, mode: "on-change", includeFrame: false, wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(detectionNode, flow);
    const n2 = helper.getNode("n2");

    const msg = await new Promise((resolve) => n2.on("input", resolve));
    expect(msg.payload.total).toBe(1);
    expect(msg.payload.detections[0].class_name).toBe("cap");
  }, 8000);

  it("tags the payload with the configured device id", async () => {
    gw = await startMockGateway({
      "GET /api/v1/detections/snapshot": (req, res) =>
        res.end(JSON.stringify({ total: 1, model: "m", detections: [{ class_name: "cap" }] })),
    });
    const flow = [
      { id: "n1", type: "detection", inferenceUrl: gw.url, mode: "on-change", deviceId: "cam-7", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(detectionNode, flow);
    const n2 = helper.getNode("n2");

    const msg = await new Promise((resolve) => n2.on("input", resolve));
    expect(msg.payload.device_id).toBe("cam-7");
  }, 8000);

  it("does not emit when there are no detections", async () => {
    gw = await startMockGateway({
      "GET /api/v1/detections/snapshot": (req, res) =>
        res.end(JSON.stringify({ total: 0, model: "m", detections: [] })),
    });
    const flow = [
      { id: "n1", type: "detection", inferenceUrl: gw.url, mode: "on-change", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(detectionNode, flow);
    const n2 = helper.getNode("n2");

    let emitted = false;
    n2.on("input", () => (emitted = true));
    // Wait past the initial fetch (setTimeout 1s + 300ms poll) to be sure.
    await new Promise((r) => setTimeout(r, 1500));
    expect(emitted).toBe(false);
  }, 8000);
});
