/**
 * @file camera-trigger node — enable/disable/toggle frame processing through the
 *   api-gateway (`/api/v1/trigger/*`), with a visual state indicator.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request } = require("../../lib/http-client");

  function TriggerNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.action = config.action || "toggle";

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    node.on("input", function (msg) {
      let action = msg.action || node.action;

      if (action === "payload") {
        action = msg.payload === true ? "enable" : "disable";
      }

      function applyAction(currentStatus) {
        if (action === "toggle") {
          action = currentStatus.trigger_enabled ? "disable" : "enable";
        }

        const path = `/api/v1/trigger/${action}`;
        request(node.inferenceUrl, "POST", path, null, (err, body) => {
          if (err) {
            node.error("Trigger request failed: " + err.message, msg);
            node.status({ fill: "red", shape: "ring", text: "error" });
            return;
          }
          const enabled = body.trigger_enabled;
          node.status({
            fill: enabled ? "green" : "red",
            shape: "dot",
            text: enabled ? "enabled" : "disabled",
          });
          msg.payload = body;
          node.send(msg);
        });
      }

      request(node.inferenceUrl, "GET", "/api/v1/trigger/status", null, (err, status) => {
        if (err) {
          if (action !== "toggle") {
            applyAction({ trigger_enabled: null });
          } else {
            node.error("Cannot reach inference service: " + err.message, msg);
            node.status({ fill: "red", shape: "ring", text: "unreachable" });
          }
          return;
        }
        applyAction(status);
      });
    });
  }

  RED.nodes.registerType("camera-trigger", TriggerNode);
};
