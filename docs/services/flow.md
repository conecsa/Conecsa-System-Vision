# Flow

Automation and integration flows (built on Node-RED) on port 1880. The
`conecsa-system-vision` custom node package lives in
`flow/nodes/conecsa-system-vision/`, is auto-registered through its
`package.json`, and is also published to npm as
[`@conecsa/node-red-contrib-conecsa-system-vision`](https://www.npmjs.com/package/@conecsa/node-red-contrib-conecsa-system-vision)
so any Node-RED can drive devices through a hub. Includes 9 nodes in the
**Conecsa** category plus one configuration node:

| Node (type id) | Description |
|---|---|
| **`camera-trigger`** (`conecsa-camera-trigger`) | Controls the processing trigger (`enable`, `disable`, `toggle`) with a visual state indicator |
| **`stats`** (`conecsa-stats`) | Subscribes to the `/api/v1/stats/stream` SSE endpoint; emits `{ detections, fps, inference_time, frames_with_detections }`. In `on-change` mode emits only when `detections` changes — fps and inference_time noise is ignored. In `interval` mode throttles the freshest snapshot to once every N seconds. Auto-reconnects on disconnect |
| **`detection`** (`conecsa-detection`) | Per-class breakdown of active detections; `on-change` or interval mode; supports the processed frame in base64 |
| **`threshold`** (`conecsa-threshold`) | Sets the confidence or overlay threshold (0–1); syncs with the backend at startup, every 5s and over the event stream |
| **`detection-models`** (`conecsa-detection-models`) | Lists available models or selects the active model by name |
| **`start-stop`** (`conecsa-start-stop`) | Starts/stops/toggles the detection engine. Subscribes to `/api/v1/events/stream` so the badge reflects `is_running` in real time regardless of which client triggered the change, and emits `{ payload: { is_running } }` on every state transition |
| **`system-status`** (`conecsa-system-status`) | Collects system metrics (CPU, RAM, disk, temperature, GPU) on demand or on an interval |
| **`reset-stats`** (`conecsa-reset-stats`) | Resets the detection counter and/or statistics (`all`, `counter`, `stats`) |
| **`gpio`** (`conecsa-gpio`) | Drives a GPIO output pin (29/31/33) HIGH/LOW. Select the pin and action (`high`, `low`, `toggle`, `payload`); `payload` maps `msg.payload` (`true`=HIGH). Subscribes to `/api/v1/events/stream` so the status badge reflects the pin's level in real time regardless of which client changed it, and emits on external transitions |
| **`conecsa-hub`** (configuration) | Connection to a hub's [Developer API](hub-vision.md#developer-api): host, port, API key, CA certificate, verify |

Type ids carry the `conecsa-` prefix (since 1.1.0) so they cannot collide with
other palettes; the palette labels stay short. Each node ships an in-editor
help panel (the `data-help-name` block in its `.html` file) that documents its
configuration fields and message output.

## Connecting the nodes

Every node has three connection fields, shared through `lib/node-base.js`
(`resolveTarget`) and `lib/http-client.js`:

- **Hub** + **Device** — *hub mode*. Select a `conecsa-hub` configuration (the
  hub's IP, port `8443`, the API key and the `conecsa-hub-ca.crt` from the
  hub's **Settings → Developer**) and one of its paired devices (the list is
  fetched from the hub once the configuration is deployed). Requests then go to
  `https://<hub>:<port>/devices/<device>/api/...` with `X-Api-Key`, over TLS
  verified against the hub CA; the hub forwards them to the device over mTLS
  and the device audit shows actor `api-key`. This is how an external Node-RED
  (an ERP's, a plant's) reaches devices.
- **API endpoint** — *direct mode*, when no hub is selected: a base URL,
  falling back to the `INFERENCE_URL` environment variable and then
  `http://api-gateway:5000`. This is what the seeded flow inside the device
  uses (`docker-compose.yml` sets `INFERENCE_URL` for the `flow` service).

Non-2xx answers (a wrong key → `401`, hub Developer API off → `503`, device
offline) surface as node errors (catchable with a **catch** node) and a red
status ring. The URL is resolved when the node is created; there is no
per-message URL override.

The web interface is at `http://localhost:1880`; inside the device image the
package is copied into `node_modules` by `flow/Dockerfile`. Tests:
`cd flow/nodes/conecsa-system-vision && npm test` (jest, with a mock gateway
and an HTTPS mock hub). Publishing to npm is manual — see the package README.

## Detections and the fleet hub

Devices no longer push detections anywhere. To aggregate a fleet, the
[`hub-vision`](hub-vision.md) app **pulls** each paired device's detections over
mTLS automatically — no `http request` node or hub URL is configured in the Flow.
See [Fleet hub → Detection pull](hub-vision.md#detection-pull).
