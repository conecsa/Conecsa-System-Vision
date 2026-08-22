"use strict";
const helper = require("node-red-node-test-helper");
const { startMockGateway } = require("./_mock-gateway");

// Every node module registers exactly one type; assert each loads and registers
// cleanly. Behaviour of the logic-carrying nodes is covered in their own specs.
const NODES = [
  { file: "../nodes/trigger/trigger.js", type: "conecsa-camera-trigger" },
  { file: "../nodes/stats/stats.js", type: "conecsa-stats" },
  { file: "../nodes/detection/detection.js", type: "conecsa-detection" },
  { file: "../nodes/threshold/threshold.js", type: "conecsa-threshold" },
  { file: "../nodes/detection-models/detection-models.js", type: "conecsa-detection-models" },
  { file: "../nodes/start-stop/start-stop.js", type: "conecsa-start-stop" },
  { file: "../nodes/system-status/system-status.js", type: "conecsa-system-status" },
  { file: "../nodes/reset-stats/reset-stats.js", type: "conecsa-reset-stats" },
  { file: "../nodes/gpio/gpio.js", type: "conecsa-gpio" },
];
const hubNode = require("../nodes/hub/hub.js");

helper.init(require.resolve("node-red"));

describe("node registration", () => {
  let gw;

  beforeEach((done) => { helper.startServer(done); });
  afterEach(async () => {
    await helper.unload();
    await new Promise((r) => helper.stopServer(r));
    if (gw) await gw.close();
    gw = null;
  });

  it('loads and registers the "conecsa-hub" config node', async () => {
    await helper.load(hubNode, [{ id: "h1", type: "conecsa-hub", host: "127.0.0.1", port: 1 }]);
    const h1 = helper.getNode("h1");
    expect(h1).toBeDefined();
    expect(h1.type).toBe("conecsa-hub");
    expect(h1.port).toBe(1);
  });

  for (const { file, type } of NODES) {
    it(`loads and registers "${type}"`, async () => {
      gw = await startMockGateway({});
      const node = require(file);
      await helper.load(node, [{ id: "n1", type, inferenceUrl: gw.url }]);
      const n1 = helper.getNode("n1");
      expect(n1).toBeDefined();
      expect(n1.type).toBe(type);
      expect(n1.targetMode).toBe("direct");
    });
  }
});
