# @conecsa/node-red-contrib-conecsa-system-vision

Node-RED nodes for [Conecsa System Vision](https://github.com/conecsa/Conecsa-System-Vision)
— real-time object detection on NVIDIA Jetson devices. The nodes start and stop
detection, stream statistics and detections, tune thresholds, switch models,
read system health, reset counters and drive GPIO pins.

They work in two ways:

- **Through a Conecsa hub (hub-vision).** Devices only answer to their hub, so
  from any Node-RED outside the device you go through the hub's
  **Developer API**: one `conecsa-hub` configuration (host, port, API key, CA
  certificate) shared by all nodes, and a **Device** picked per node. Requests
  become `https://<hub>:<port>/devices/<device>/api/...`.
- **Directly** — inside a device (the Flow container ships this package) the
  nodes call the local api-gateway (`http://api-gateway:5000`) with no hub.

## Install

From the Node-RED palette manager (search for `conecsa`) or:

```bash
cd ~/.node-red
npm install @conecsa/node-red-contrib-conecsa-system-vision
```

Requires Node-RED ≥ 3.1 and Node.js ≥ 18.

## Connect to a hub

1. On the hub, sign in as owner/admin and open **Settings → Developer**. Turn
   **Accept requests** on; the hub shows its URL (`https://<hub-ip>:8443`) and
   the API key (copy it). Click **Download CA certificate** to save
   `conecsa-hub-ca.crt`.
2. In Node-RED, drag any Conecsa node, open it and next to **Hub** click the
   pencil to add a `conecsa-hub` configuration: the hub's IP address, the port
   (8443 unless you changed it on the hub), the API key, and **Upload** the CA
   file. Keep **Verify** on.
3. **Deploy** once (the hub configuration must be deployed before it can list
   devices), reopen the node and pick the **Device**. The **API endpoint** row
   shows the resulting route, e.g.
   `https://172.29.96.198:8443/devices/conecsa-084936`.

The API key and the certificate are stored as Node-RED credentials (encrypted
in `flows_cred.json`, not included when you export a flow). Use the hub's IP as
host — the hub's certificate lists its LAN addresses. Rotating the key on the
hub requires updating the `conecsa-hub` configuration.

Without a hub, the **API endpoint** field is a direct base URL; when empty the
nodes use the `INFERENCE_URL` environment variable, then
`http://api-gateway:5000`.

Import → Examples → *@conecsa/node-red-contrib-conecsa-system-vision* has a ready flow
for each mode.

## Nodes

All nodes live in the **Conecsa** palette category.

| Node (type id) | Description |
|---|---|
| **start/stop** (`conecsa-start-stop`) | Starts/stops/toggles detection. Follows the device's event stream so its badge and output reflect `is_running` whoever changed it; emits `{ payload: { is_running } }` on each transition. |
| **camera-trigger** (`conecsa-camera-trigger`) | Enables/disables/toggles frame processing with a visual state indicator. |
| **stats** (`conecsa-stats`) | Subscribes to the stats stream; emits `{ detections, fps, inference_time, frames_with_detections }` on change or on an interval. |
| **detection** (`conecsa-detection`) | Per-class breakdown of the current detections (optionally with the processed frame as base64), on change or on an interval. |
| **threshold** (`conecsa-threshold`) | Sets the confidence or overlay threshold (0–1); stays in sync with the device. |
| **detection models** (`conecsa-detection-models`) | Lists the available models or selects the active one by name. |
| **system status** (`conecsa-system-status`) | CPU, RAM, disk, temperature and GPU metrics on demand or on an interval. |
| **reset stats** (`conecsa-reset-stats`) | Resets the detection counter and/or statistics. |
| **gpio** (`conecsa-gpio`) | Drives a GPIO output pin (29/31/33) HIGH/LOW and follows external changes. |
| **conecsa-hub** (configuration) | Connection to a hub's Developer API (host, port, API key, CA, verify). |

Each node's in-editor help (the ⓘ panel) documents its configuration, inputs
and outputs in detail.

## Errors

A device that is offline, a wrong API key (`HTTP 401`) or a hub whose Developer
API is turned off (`HTTP 503`) is reported through the node's status badge and
`node.error` (catchable with a **catch** node).

## Upgrading from 1.0.0

1.0.0 only ever shipped inside the device image with unprefixed type ids
(`stats`, `start-stop`, …). 1.1.0 prefixes them with `conecsa-`; flows built
with the old ids need their `"type"` values rewritten (export → edit → import).

## Development

```bash
npm install
npm test            # jest + node-red-node-test-helper, mock gateway and mock hub (HTTPS)
npm pack --dry-run  # what would be published
```

Publishing (maintainers): `npm login`, then `npm publish --access public` from
this directory — `prepublishOnly` runs the test suite first.

## License

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). "Conecsa" and
"System Vision" are trademarks of Conecsa.
