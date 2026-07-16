/**
 * @file stats node — subscribes to the `/api/v1/stats/stream` SSE endpoint and
 *   emits `{ detections, fps, inference_time, frames_with_detections }`.
 *   `on-change` mode emits only when `detections` changes; `interval` mode
 *   throttles the freshest snapshot to once every N seconds. Auto-reconnects.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, subscribeSSE } = require("../../lib/http-client");

  function StatsNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.mode = config.mode || "on-change";
    node.interval = (parseFloat(config.interval) || 2) * 1000;

    node.status({ fill: "grey", shape: "ring", text: "connecting" });

    // Used by on-change mode: emit only when the detection count
    // changes. fps / inference_time fluctuate every frame and would
    // otherwise drown the output in noise.
    let lastDetections = null;

    // For interval mode: hold the freshest payload and flush it every
    // `node.interval` ms via a setInterval timer.
    let latestPayload = null;
    let throttleTimer = null;

    function emit(payload) {
      node.status({
        fill: "blue",
        shape: "dot",
        text: `detections: ${payload.detections}`,
      });
      node.send({ payload });
    }

    function handleEvent(body) {
      const payload = {
        detections: body.detections,
        fps: body.fps,
        inference_time: body.inference_time,
        frames_with_detections: body.frames_with_detections,
      };

      if (node.mode === "on-change") {
        // Only emit when the detection count changes. The first event
        // (lastDetections === null) is always emitted so downstream nodes
        // see the starting value.
        if (payload.detections === lastDetections) {
          return;
        }
        lastDetections = payload.detections;
        emit(payload);
      } else {
        // interval mode: remember the freshest snapshot; the throttle
        // timer below decides when to actually flush it downstream.
        latestPayload = payload;
        if (!throttleTimer) {
          throttleTimer = setInterval(() => {
            if (latestPayload) emit(latestPayload);
          }, node.interval);
        }
      }
    }

    const stream = subscribeSSE(node.inferenceUrl, "/api/v1/stats/stream", {
      onEvent: handleEvent,
      onError: () => {
        node.status({ fill: "red", shape: "ring", text: "error" });
      },
    });

    node.on("close", function () {
      if (throttleTimer) {
        clearInterval(throttleTimer);
        throttleTimer = null;
      }
      if (stream) stream.close();
    });
  }

  RED.nodes.registerType("stats", StatsNode);
};
