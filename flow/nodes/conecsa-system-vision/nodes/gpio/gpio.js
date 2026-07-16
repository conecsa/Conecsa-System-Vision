/**
 * @file gpio node — drives a single GPIO output pin HIGH/LOW. The pin and the
 *   action (high/low/toggle/payload) are configured on the node. It subscribes
 *   to `/api/v1/events/stream` so the status badge live-updates whenever the
 *   pin changes on any client, and emits `{ payload: { pin, level, ... } }`.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request, subscribeSSE } = require("../../lib/http-client");

  function GpioNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.pin = parseInt(config.pin, 10);
    node.action = config.action || "high";
    const nodeSource = `node-red:${node.id}`;

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    // Cached level for this pin, kept fresh from status reads and the SSE
    // stream. `null` until the first read; used by the toggle action so it does
    // not have to re-fetch on every input.
    let currentLevel = null;

    function updateStatus(level) {
      node.status({
        fill: level ? "green" : "grey",
        shape: "dot",
        text: `pin ${node.pin} ${level ? "HIGH" : "LOW"}`,
      });
    }

    // Read this pin's current level from the gateway, refresh the cache + badge,
    // and (when `emit`) send downstream only on an actual change — so external
    // updates picked up over SSE flow through, but the initial sync does not.
    function readPinFromStatus(emit, event) {
      request(node.inferenceUrl, "GET", "/api/v1/gpio/status", null, (err, status) => {
        if (err || !status || !status.pin_states) {
          node.status({ fill: "red", shape: "ring", text: "unreachable" });
          return;
        }
        const level = !!status.pin_states[String(node.pin)];
        const changed = currentLevel !== null && currentLevel !== level;
        currentLevel = level;
        updateStatus(level);
        if (emit && changed) {
          node.send({ payload: { pin: node.pin, level: level, event: event && event.type } });
        }
      });
    }

    // Sync this pin's level when the flow starts and keep polling as a fallback.
    readPinFromStatus();
    const pollInterval = setInterval(readPinFromStatus, 5000);

    // Live-update the badge whenever GPIO state changes on any client. The
    // gateway publishes `gpio_changed` events (keys: ["gpio"]) for both the
    // trigger toggle and per-pin writes; ignore our own writes (handled below).
    const eventStream = subscribeSSE(node.inferenceUrl, "/api/v1/events/stream", {
      onEvent: (event) => {
        const keys = Array.isArray(event.keys) ? event.keys : [];
        const relevant =
          event.type === "state_snapshot" ||
          event.type === "gpio_changed" ||
          keys.includes("gpio");
        if (!relevant || event.source === nodeSource) return;
        readPinFromStatus(event.type !== "state_snapshot", event);
      },
      onError: () => {
        node.status({ fill: "red", shape: "ring", text: "events unreachable" });
      },
    });

    // Drive the pin to `level` and emit on success.
    function setPin(level, msg) {
      request(
        node.inferenceUrl,
        "POST",
        "/api/v1/gpio/pin",
        { pin: node.pin, level: level },
        (err, body) => {
          if (err) {
            node.error("GPIO request failed: " + err.message, msg);
            node.status({ fill: "red", shape: "ring", text: "error" });
            return;
          }
          currentLevel = level;
          updateStatus(level);
          msg.payload = { pin: node.pin, level: level, success: !!(body && body.success) };
          node.send(msg);
        },
        { source: nodeSource },
      );
    }

    node.on("input", function (msg) {
      let action = msg.action || node.action;

      if (action === "payload") {
        setPin(!!msg.payload, msg);
        return;
      }

      if (action === "toggle") {
        if (currentLevel === null) {
          // SSE/status sync has not delivered a level yet; fall back to a
          // one-shot status read so the toggle still works.
          request(node.inferenceUrl, "GET", "/api/v1/gpio/status", null, (err, status) => {
            if (err || !status || !status.pin_states) {
              node.error(
                "Cannot read GPIO status for toggle: " + (err ? err.message : "no pin_states"),
                msg,
              );
              node.status({ fill: "red", shape: "ring", text: "unreachable" });
              return;
            }
            setPin(!status.pin_states[String(node.pin)], msg);
          });
          return;
        }
        setPin(!currentLevel, msg);
        return;
      }

      // "high" / "low"
      setPin(action === "high", msg);
    });

    node.on("close", function () {
      clearInterval(pollInterval);
      if (eventStream) eventStream.close();
    });
  }

  RED.nodes.registerType("gpio", GpioNode);
};
