"use strict";
const helper = require("node-red-node-test-helper");
const statsNode = require("../nodes/stats/stats.js");
const { startMockGateway } = require("./_mock-gateway");

helper.init(require.resolve("node-red"));

describe("stats node", () => {
  let gw;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (gw) await gw.close();
    gw = null;
  });

  it("registers with the default on-change mode", async () => {
    gw = await startMockGateway({});
    await helper.load(statsNode, [{ id: "n1", type: "stats", inferenceUrl: gw.url }]);
    const n1 = helper.getNode("n1");
    expect(n1.type).toBe("stats");
    expect(n1.mode).toBe("on-change");
  });

  it("emits the mapped payload on the first stats event", async () => {
    let sseRes;
    gw = await startMockGateway({
      "GET /api/v1/stats/stream": (req, res) => {
        res.writeHead(200, { "Content-Type": "text/event-stream" });
        sseRes = res;
      },
    });
    const flow = [
      { id: "n1", type: "stats", inferenceUrl: gw.url, mode: "on-change", wires: [["n2"]] },
      { id: "n2", type: "helper" },
    ];
    await helper.load(statsNode, flow);
    const n2 = helper.getNode("n2");

    const output = new Promise((resolve) => n2.on("input", resolve));
    // Let the SSE connection establish, then push one event.
    await new Promise((r) => setTimeout(r, 100));
    sseRes.write(
      "data: " +
        JSON.stringify({
          detections: 3,
          fps: 30,
          inference_time: 12,
          frames_with_detections: 100,
        }) +
        "\n\n"
    );

    const msg = await output;
    expect(msg.payload).toEqual({
      detections: 3,
      fps: 30,
      inference_time: 12,
      frames_with_detections: 100,
    });
  });
});
