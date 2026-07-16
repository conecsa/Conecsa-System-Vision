/**
 * @file start-stop node — starts/stops/toggles the detection engine. Subscribes
 *   to `/api/v1/events/stream` so the badge reflects `is_running` in real time
 *   regardless of which client changed it, emitting `{ payload: { is_running } }`
 *   on every state transition.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request, subscribeSSE } = require("../../lib/http-client");

  function StartStopNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.action = config.action || "toggle";
    const nodeSource = `node-red:${node.id}`;

    node.status({ fill: "grey", shape: "ring", text: "connecting" });

    // Authoritative state cached from the SSE stream. `null` until the
    // first event arrives; used by the toggle action so it does not
    // have to re-fetch on every input.
    let isRunning = null;

    function updateStatus(running) {
      node.status({
        fill: running ? "green" : "red",
        shape: "dot",
        text: running ? "running" : "stopped",
      });
    }

    // Apply a new is_running value: update the badge and emit downstream
    // only on an actual transition. `emit=false` seeds the cached state
    // (initial snapshot / reconnect) without producing a spurious message.
    function applyRunning(running, emit) {
      const previous = isRunning;
      isRunning = running;
      updateStatus(running);
      if (emit && previous !== null && previous !== running) {
        node.send({ payload: { is_running: running } });
      }
    }

    // Seed the cached state from an authoritative /status read (used on
    // connect/reconnect, where the invalidation snapshot carries no state).
    function seedFromStatus() {
      request(node.inferenceUrl, "GET", "/api/v1/status", null, (err, status) => {
        if (err || !status) return;
        applyRunning(!!status.is_running, false);
      }, { source: nodeSource });
    }

    // Subscribe to the unified inference-service event stream so the badge —
    // AND the node's output — react on every is_running change, regardless of
    // whether the change was triggered by this node, the web UI, another flow,
    // or curl. State changes arrive as `detection_state_changed` events; the
    // stream also carries invalidation/stats traffic which we ignore here.
    const stream = subscribeSSE(node.inferenceUrl, "/api/v1/events/stream", {
      onEvent: (body) => {
        if (!body || body.type === "stats") return;
        if (body.type === "state_snapshot") {
          // Connect/reconnect: the snapshot has no state payload, so read it.
          seedFromStatus();
          return;
        }
        if (
          body.type === "detection_state_changed" &&
          body.data &&
          typeof body.data.is_running === "boolean"
        ) {
          applyRunning(body.data.is_running, true);
        }
      },
      onError: () => {
        node.status({ fill: "red", shape: "ring", text: "unreachable" });
      },
    });

    node.on("input", function (msg) {
      let action = msg.action || node.action;

      if (action === "payload") {
        action = msg.payload === true ? "start" : "stop";
      }

      function postAction(resolvedAction) {
        const path = `/api/v1/${resolvedAction}`;
        request(node.inferenceUrl, "POST", path, null, (err, _body) => {
          if (err) {
            node.error("Start/stop request failed: " + err.message, msg);
            node.status({ fill: "red", shape: "ring", text: "error" });
            return;
          }
          // No send here — the SSE callback above is the single source
          // of truth for state-change emissions. A no-op POST (start
          // when already running, etc.) intentionally produces no
          // message because no state change occurred.
        }, { source: nodeSource });
      }

      if (action === "toggle") {
        if (isRunning === null) {
          // SSE has not delivered the initial snapshot yet; fall back
          // to a one-shot status fetch so the toggle still works.
          request(node.inferenceUrl, "GET", "/api/v1/status", null, (err, status) => {
            if (err) {
              node.error("Cannot reach inference service: " + err.message, msg);
              node.status({ fill: "red", shape: "ring", text: "unreachable" });
              return;
            }
            postAction(status.is_running ? "stop" : "start");
          });
          return;
        }
        postAction(isRunning ? "stop" : "start");
      } else {
        postAction(action);
      }
    });

    node.on("close", function () {
      if (stream) stream.close();
    });
  }

  RED.nodes.registerType("start-stop", StartStopNode);
};
