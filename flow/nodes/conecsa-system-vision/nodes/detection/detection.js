/**
 * @file detection node — per-class breakdown of the active detections.
 *   `on-change` or interval mode; can include the processed frame as base64.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request } = require("../../lib/http-client");

  function DetectionNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.mode = config.mode || "on-change";
    node.interval = (parseFloat(config.interval) || 5) * 1000;
    node.includeFrame = config.includeFrame !== false;

    // Optional device identity for the conecsa-hub-vision hub (node config or
    // DEVICE_ID env). Leave empty to let the hub attribute records to the device
    // it discovered over mDNS, matched by the request's source IP. Avoid relying
    // on the container hostname here — it is not the device's host hostname.
    node.deviceId = (config.deviceId || process.env.DEVICE_ID || "").trim();

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    let timer = null;
    let lastSignature = null;

    function buildSignature(body) {
      const detections = Array.isArray(body && body.detections) ? body.detections : [];
      // Count detections by class + area label, ignoring confidence so the
      // signature stays stable frame-to-frame (used for on-change mode).
      const counts = {};
      for (const d of detections) {
        const cls = d && d.class_name ? d.class_name : "";
        const areaLabel = d && d.area && d.area.label ? d.area.label : "none";
        const key = `${cls}@${areaLabel}`;
        counts[key] = (counts[key] || 0) + 1;
      }
      const sortedCounts = {};
      for (const key of Object.keys(counts).sort()) {
        sortedCounts[key] = counts[key];
      }

      return JSON.stringify({
        detections: sortedCounts,
        total: body && typeof body.total === "number" ? body.total : 0,
        model: body && body.model ? body.model : "",
        acceleration_type: body && body.acceleration_type ? body.acceleration_type : "",
        runtime_type: body && body.runtime_type ? body.runtime_type : "",
      });
    }

    function fetchSnapshot() {
      const includeFrame = node.includeFrame ? "true" : "false";
      const path = `/api/v1/detections/snapshot?include_frame=${includeFrame}`;

      request(node.inferenceUrl, "GET", path, null, (err, body) => {
        if (err) {
          node.status({ fill: "red", shape: "ring", text: "error" });
          node.error("Detection snapshot failed: " + err.message);
          return;
        }

        if (node.mode === "on-change") {
          const signature = buildSignature(body);
          if (signature === lastSignature) {
            return;
          }
          lastSignature = signature;
        }

        const detections = Array.isArray(body.detections) ? body.detections : [];
        const total = body.total || 0;
        const classes = [...new Set(detections.map((d) => d && d.class_name).filter(Boolean))];
        const noArea = detections.filter((d) => !(d && d.area)).length;

        let statusText;
        if (total > 0) {
          statusText = `${total} obj (${classes.join(", ")})`;
          if (noArea > 0) {
            statusText += ` · ${noArea} no area`;
          }
        } else {
          statusText = "no detections";
        }

        node.status({
          fill: total > 0 ? "green" : "blue",
          shape: "dot",
          text: statusText,
        });

        // Only emit when there is at least one detection.
        if (total <= 0) {
          return;
        }

        // Tag the payload with the device identity for the hub (only when set;
        // otherwise the hub resolves the device by source IP).
        if (node.deviceId) {
          body.device_id = node.deviceId;
        }

        node.send({ payload: body });
      });
    }

    const pollInterval = node.mode === "on-change" ? 300 : node.interval;
    timer = setInterval(fetchSnapshot, pollInterval);
    setTimeout(fetchSnapshot, 1000);

    node.on("close", function () {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    });
  }

  RED.nodes.registerType("detection", DetectionNode);
};
