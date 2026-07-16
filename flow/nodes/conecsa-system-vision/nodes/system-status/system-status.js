/**
 * @file system-status node — collects system metrics (CPU, RAM, disk,
 *   temperature, GPU) from `/api/system/status` on demand or on an interval.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request } = require("../../lib/http-client");

  function SystemStatusNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.mode = config.mode || "on-demand";
    node.interval = (parseFloat(config.interval) || 10) * 1000;

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    let timer = null;

    function fetchStatus() {
      request(node.inferenceUrl, "GET", "/api/system/status", null, (err, body) => {
        if (err) {
          node.status({ fill: "red", shape: "ring", text: "error" });
          if (node.mode === "on-demand") {
            node.error("System status request failed: " + err.message);
          }
          return;
        }

        node.status({
          fill: "green",
          shape: "dot",
          text: `CPU: ${body.cpu_usage}% | RAM: ${body.ram_usage}%`,
        });

        node.send({ payload: body });
      });
    }

    if (node.mode === "interval") {
      timer = setInterval(fetchStatus, node.interval);
      setTimeout(fetchStatus, 1000);
    } else {
      node.on("input", function () {
        fetchStatus();
      });
    }

    node.on("close", function () {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    });
  }

  RED.nodes.registerType("system-status", SystemStatusNode);
};
