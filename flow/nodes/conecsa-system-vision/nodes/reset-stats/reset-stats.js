/**
 * @file reset-stats node — resets the detection counter and/or statistics via
 *   the api-gateway. Scope is one of `all`, `counter`, `stats`.
 * @param {object} RED Node-RED runtime, injected when the node type registers.
 */
module.exports = function (RED) {
  "use strict";
  const { inferenceBaseUrl, request } = require("../../lib/http-client");

  function ResetStatsNode(config) {
    RED.nodes.createNode(this, config);
    const node = this;

    node.inferenceUrl = inferenceBaseUrl(config);
    node.scope = config.scope || "all";

    node.status({ fill: "grey", shape: "ring", text: "idle" });

    function resetCounter(cb) {
      request(node.inferenceUrl, "POST", "/api/v1/counter/reset", null, cb);
    }

    function resetStats(cb) {
      request(node.inferenceUrl, "POST", "/api/v1/stats/reset", null, cb);
    }

    node.on("input", function (msg) {
      const scope = msg.scope || node.scope;

      function done(err) {
        if (err) {
          node.error("Reset failed: " + err.message, msg);
          node.status({ fill: "red", shape: "ring", text: "error" });
          return;
        }

        node.status({
          fill: "green",
          shape: "dot",
          text: "reset: " + scope,
        });

        msg.payload = { reset: scope, success: true };
        node.send(msg);
      }

      if (scope === "counter") {
        resetCounter(done);
      } else if (scope === "stats") {
        resetStats(done);
      } else {
        // "all" — reset both; counter first, then stats
        resetCounter(function (err) {
          if (err) return done(err);
          resetStats(done);
        });
      }
    });
  }

  RED.nodes.registerType("reset-stats", ResetStatsNode);
};
