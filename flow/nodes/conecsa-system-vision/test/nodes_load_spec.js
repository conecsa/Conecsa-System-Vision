"use strict";
const helper = require("node-red-node-test-helper");
const { startMockGateway } = require("./_mock-gateway");

// Every node module registers exactly one type; assert each loads and registers
// cleanly. Behaviour of the logic-carrying nodes is covered in their own specs.
const NODES = [
  { file: "../nodes/trigger/trigger.js", type: "camera-trigger" },
  { file: "../nodes/detection-models/detection-models.js", type: "detection-models" },
  { file: "../nodes/start-stop/start-stop.js", type: "start-stop" },
  { file: "../nodes/system-status/system-status.js", type: "system-status" },
  { file: "../nodes/reset-stats/reset-stats.js", type: "reset-stats" },
  { file: "../nodes/gpio/gpio.js", type: "gpio" },
];

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

  for (const { file, type } of NODES) {
    it(`loads and registers "${type}"`, async () => {
      gw = await startMockGateway({});
      const node = require(file);
      await helper.load(node, [{ id: "n1", type, inferenceUrl: gw.url }]);
      const n1 = helper.getNode("n1");
      expect(n1).toBeDefined();
      expect(n1.type).toBe(type);
    });
  }
});
