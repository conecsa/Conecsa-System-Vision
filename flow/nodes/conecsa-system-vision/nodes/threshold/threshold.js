/**
 * @file threshold node — sets the confidence or IoU/NMS threshold (0–1) via the
 *   api-gateway; syncs with the backend at startup and every 5s over SSE.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request, subscribeSSE } = require("../../lib/http-client");

  function ThresholdNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.thresholdType = config.thresholdType || "confidence";
    node.value = parseFloat(config.value) || 0.5;
    const nodeSource = `node-red:${node.id}`;

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    function readCurrentThresholdFromStatus(emit, event) {
      request(node.inferenceUrl, "GET", "/api/v1/status", null, (err, status) => {
        if (err) {
          node.status({ fill: "red", shape: "ring", text: "unreachable" });
          return;
        }

        const currentValue =
          node.thresholdType === "overlay"
            ? status.overlay_threshold
            : status.confidence_threshold;

        if (typeof currentValue === "number") {
          node.value = currentValue;
          node.status({
            fill: "blue",
            shape: "dot",
            text: `${node.thresholdType}: ${currentValue.toFixed(2)}`,
          });
          if (emit) {
            node.send({
              payload: {
                thresholdType: node.thresholdType,
                threshold: currentValue,
                event,
              },
            });
          }
        }
      });
    }

    // Sync threshold value from backend when the flow starts and keep polling.
    readCurrentThresholdFromStatus();
    const pollInterval = setInterval(readCurrentThresholdFromStatus, 5000);

    const eventStream = subscribeSSE(node.inferenceUrl, "/api/v1/events/stream", {
      onEvent: (event) => {
        const keys = Array.isArray(event.keys) ? event.keys : [];
        const relevant =
          event.type === "state_snapshot" ||
          event.type === "thresholds_changed" ||
          keys.includes("thresholds") ||
          keys.includes("status");
        if (!relevant || event.source === nodeSource) return;
        readCurrentThresholdFromStatus(event.type !== "state_snapshot", event);
      },
      onError: () => {
        node.status({ fill: "red", shape: "ring", text: "events unreachable" });
      },
    });

    node.on("close", function () {
      clearInterval(pollInterval);
      if (eventStream) eventStream.close();
    });

    node.on("input", function (msg) {
      const value = typeof msg.payload === "number" ? msg.payload : node.value;
      const type = msg.thresholdType || node.thresholdType;

      const path =
        type === "overlay"
          ? "/api/v1/overlay_threshold"
          : "/api/v1/threshold";

      request(node.inferenceUrl, "POST", path, { threshold: value }, (err, body) => {
        if (err) {
          node.error("Threshold request failed: " + err.message, msg);
          node.status({ fill: "red", shape: "ring", text: "error" });
          return;
        }

        node.status({
          fill: "green",
          shape: "dot",
          text: `${type}: ${body.threshold.toFixed(2)}`,
        });

        if (typeof body.threshold === "number") {
          node.value = body.threshold;
        }

        msg.payload = body;
        node.send(msg);
      }, { source: nodeSource });
    });
  }

  RED.nodes.registerType("threshold", ThresholdNode);
};
