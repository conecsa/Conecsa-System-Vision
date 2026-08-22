/**
 * @file Shared node scaffolding. Every Conecsa node starts the same way —
 *   createNode, work out where the api-gateway is (through a hub, or directly),
 *   paint an initial ring status — and that boilerplate lived copied in each
 *   node. The HTTP/SSE transport is in ./http-client; this module owns only the
 *   node lifecycle scaffold.
 */
"use strict";

const { inferenceBaseUrl } = require("./http-client");

/**
 * Decide how a node reaches the api-gateway.
 *
 * Hub mode: the node references a `conecsa-hub` config node and names a
 * device — requests go to `https://<hub>:<port>/devices/<device>/api/...`
 * with the hub's API key and CA. Direct mode (no hub, or a hub without a
 * device): the legacy base URL chain — per-node "API endpoint" →
 * `INFERENCE_URL` → `http://api-gateway:5000` — which is what the Flow
 * container on the device itself uses.
 *
 * @param {object} RED Node-RED runtime.
 * @param {object} config The node's editor configuration.
 * @returns {{ target: string|object, baseUrl: string, mode: "hub"|"direct", hub: object|null, device: string, warning: string|null }}
 */
function resolveTarget(RED, config) {
  const hubId = config && config.hub;
  const hub = hubId ? RED.nodes.getNode(hubId) : null;
  const device = String((config && config.device) || "").trim();

  if (hub && device) {
    const target = hub.target(device);
    return { target, baseUrl: target.baseUrl, mode: "hub", hub, device, warning: null };
  }

  let warning = null;
  if (hubId && !hub) {
    warning = "hub configuration not found (is it deployed?) — using the direct API endpoint";
  } else if (hub && !device) {
    warning = "a hub is selected but no device — using the direct API endpoint";
  }
  const baseUrl = inferenceBaseUrl(config);
  return { target: baseUrl, baseUrl, mode: "direct", hub: null, device: "", warning };
}

/**
 * Standard node initialization: registers the node with the runtime, resolves
 * `node.target` (what the node passes to `request`/`subscribeSSE`), and seeds
 * the status ring.
 *
 * @param {object} RED Node-RED runtime.
 * @param {object} node The node instance (`this` inside the constructor).
 * @param {object} config The node's editor configuration.
 * @param {string} [statusText] Initial grey-ring status ("idle" by default).
 */
function initNode(RED, node, config, statusText = "idle") {
  RED.nodes.createNode(node, config);
  const resolved = resolveTarget(RED, config);
  node.target = resolved.target;
  node.inferenceUrl = resolved.baseUrl;
  node.targetMode = resolved.mode;
  node.device = resolved.device;
  if (resolved.warning && typeof node.warn === "function") {
    node.warn(resolved.warning);
  }
  node.status({ fill: "grey", shape: "ring", text: statusText });
}

module.exports = { initNode, resolveTarget };
