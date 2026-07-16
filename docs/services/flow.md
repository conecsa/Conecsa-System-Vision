# Flow

Automation and integration flows (built on Node-RED) on port 1880. The
`conecsa-system-vision` custom node package lives in
`flow/nodes/conecsa-system-vision/` and is
auto-registered through `package.json`. Includes 9 nodes in the **Conecsa**
category:

| Node | Description |
|---|---|
| **`camera-trigger`** | Controls the processing trigger (`enable`, `disable`, `toggle`) with a visual state indicator |
| **`stats`** | Subscribes to the `/api/v1/stats/stream` SSE endpoint; emits `{ detections, fps, inference_time, frames_with_detections }`. In `on-change` mode emits only when `detections` changes — fps and inference_time noise is ignored. In `interval` mode throttles the freshest snapshot to once every N seconds. Auto-reconnects on disconnect |
| **`detection`** | Per-class breakdown of active detections; `on-change` or interval mode; supports the processed frame in base64 |
| **`threshold`** | Sets confidence or IoU/NMS threshold (0–1); syncs with the backend at startup and every 5s |
| **`detection-models`** | Lists available models or selects the active model by name |
| **`start-stop`** | Starts/stops/toggles the detection engine. Subscribes to `/api/v1/events/stream` so the badge reflects `is_running` in real time regardless of which client triggered the change, and emits `{ payload: { is_running } }` on every state transition |
| **`system-status`** | Collects system metrics (CPU, RAM, disk, temperature, GPU) on demand or on an interval |
| **`reset-stats`** | Resets the detection counter and/or statistics (`all`, `counter`, `stats`) |
| **`gpio`** | Drives a GPIO output pin (29/31/33) HIGH/LOW. Select the pin and action (`high`, `low`, `toggle`, `payload`); `payload` maps `msg.payload` (`true`=HIGH). Subscribes to `/api/v1/events/stream` so the status badge reflects the pin's level in real time regardless of which client changed it, and emits on external transitions |

All nodes share `lib/http-client.js` and allow overriding the
inference-service URL via configuration or via `msg`. Each node ships an
in-editor help panel (the `data-help-name` block in its `.html` file) that
documents its configuration fields and message output.

The web interface is at `http://localhost:1880`; the nodes are auto-registered
via `package.json` in `flow/nodes/conecsa-system-vision/`.

## Detections and the fleet hub

Devices no longer push detections anywhere. To aggregate a fleet, the
[`hub-vision`](hub-vision.md) app **pulls** each paired device's detections over
mTLS automatically — no `http request` node or hub URL is configured in the Flow.
See [Fleet hub → Detection pull](hub-vision.md#detection-pull).
