/**
 * @file detection-models node — lists available models or selects the active
 *   model by name via the api-gateway (`/api/v1/models`, `/api/v1/model/select`).
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request, subscribeSSE } = require("../../lib/http-client");

  function DetectionModelsNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.action = config.action || "list";
    node.modelName = config.modelName || "";
    const nodeSource = `node-red:${node.id}`;

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    function fetchModels(msg, emit, event) {
      request(node.inferenceUrl, "GET", "/api/v1/models", null, (err, body) => {
        if (err) {
          node.error("Model list failed: " + err.message, msg);
          node.status({ fill: "red", shape: "ring", text: "error" });
          return;
        }

        const models = body.models || body;
        const active = models.find((m) => m.is_active);
        node.status({
          fill: "blue",
          shape: "dot",
          text: `${models.length} model(s)` + (active ? ` [${active.name}]` : ""),
        });
        if (emit) {
          const out = msg || {};
          out.payload = { models, active, event };
          node.send(out);
        }
      });
    }

    const eventStream = subscribeSSE(node.inferenceUrl, "/api/v1/events/stream", {
      onEvent: (event) => {
        const keys = Array.isArray(event.keys) ? event.keys : [];
        const relevant =
          event.type === "state_snapshot" ||
          event.type === "model_changed" ||
          event.type === "models_changed" ||
          event.type === "classes_changed" ||
          keys.includes("models") ||
          keys.includes("classes");
        if (!relevant || event.source === nodeSource) return;
        fetchModels(null, event.type !== "state_snapshot", event);
      },
      onError: () => {
        node.status({ fill: "red", shape: "ring", text: "events unreachable" });
      },
    });

    node.on("input", function (msg) {
      const action = msg.action || node.action;
      const modelName = msg.modelName || node.modelName;

      if (action === "select") {
        if (!modelName) {
          node.error("No model name specified", msg);
          node.status({ fill: "red", shape: "ring", text: "no model name" });
          return;
        }

        request(
          node.inferenceUrl,
          "POST",
          "/api/v1/model/select",
          { model_name: modelName },
          (err, body) => {
            if (err) {
              node.error("Model select failed: " + err.message, msg);
              node.status({ fill: "red", shape: "ring", text: "error" });
              return;
            }
            node.status({
              fill: "green",
              shape: "dot",
              text: `selected: ${modelName}`,
            });
            msg.payload = body;
            node.send(msg);
          },
          { source: nodeSource }
        );
      } else {
        fetchModels(msg, true, null);
      }
    });

    node.on("close", function () {
      if (eventStream) eventStream.close();
    });
  }

  RED.nodes.registerType("detection-models", DetectionModelsNode);
};
