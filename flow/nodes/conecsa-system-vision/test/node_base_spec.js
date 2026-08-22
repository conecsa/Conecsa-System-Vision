// The shared node scaffold must register the node, work out how to reach the
// api-gateway (through a hub or directly), and seed the status ring exactly
// like the copies it replaced.
const { initNode, resolveTarget } = require("../lib/node-base");

function fakeRed(hubs = {}) {
  return { nodes: { createNode: jest.fn(), getNode: jest.fn((id) => hubs[id] || null) } };
}

function fakeNode() {
  return { status: jest.fn(), warn: jest.fn() };
}

function fakeHub() {
  return {
    target: (device) => ({
      baseUrl: "https://hub:8443/devices/" + device,
      headers: { "X-Api-Key": "k".repeat(32) },
      tls: { rejectUnauthorized: true, ca: "PEM" },
    }),
  };
}

describe("initNode", () => {
  it("registers, resolves the base URL, and seeds an idle ring", () => {
    const RED = fakeRed();
    const node = fakeNode();
    const config = { inferenceUrl: "http://gateway:5000" };
    initNode(RED, node, config);
    expect(RED.nodes.createNode).toHaveBeenCalledWith(node, config);
    expect(node.inferenceUrl).toBe("http://gateway:5000");
    expect(node.target).toBe("http://gateway:5000");
    expect(node.targetMode).toBe("direct");
    expect(node.status).toHaveBeenCalledWith({
      fill: "grey", shape: "ring", text: "idle",
    });
    expect(node.warn).not.toHaveBeenCalled();
  });

  it("accepts a custom seed status", () => {
    const node = fakeNode();
    initNode(fakeRed(), node, {}, "connecting");
    expect(node.status).toHaveBeenCalledWith({
      fill: "grey", shape: "ring", text: "connecting",
    });
  });

  it("routes through the hub when a hub and a device are configured", () => {
    const node = fakeNode();
    initNode(fakeRed({ h1: fakeHub() }), node, { hub: "h1", device: " dev-1 " });
    expect(node.targetMode).toBe("hub");
    expect(node.device).toBe("dev-1");
    expect(node.target.baseUrl).toBe("https://hub:8443/devices/dev-1");
    expect(node.target.headers["X-Api-Key"]).toBe("k".repeat(32));
    expect(node.inferenceUrl).toBe("https://hub:8443/devices/dev-1");
    expect(node.warn).not.toHaveBeenCalled();
  });

  it("warns and falls back to direct when the hub is selected without a device", () => {
    const node = fakeNode();
    initNode(fakeRed({ h1: fakeHub() }), node, { hub: "h1", device: "", inferenceUrl: "http://direct:1" });
    expect(node.targetMode).toBe("direct");
    expect(node.target).toBe("http://direct:1");
    expect(node.warn).toHaveBeenCalledWith(expect.stringMatching(/no device/));
  });

  it("warns and falls back to direct when the hub config is missing", () => {
    const node = fakeNode();
    initNode(fakeRed(), node, { hub: "gone", device: "dev-1", inferenceUrl: "http://direct:1" });
    expect(node.targetMode).toBe("direct");
    expect(node.warn).toHaveBeenCalledWith(expect.stringMatching(/not found/));
  });
});

describe("resolveTarget", () => {
  it("keeps the direct precedence chain", () => {
    const r = resolveTarget(fakeRed(), { inferenceUrl: "http://x:1" });
    expect(r).toMatchObject({ mode: "direct", baseUrl: "http://x:1", hub: null, device: "", warning: null });
  });
});
