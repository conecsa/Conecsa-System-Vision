# HTTP API reference

All HTTP endpoints are served by the **api-gateway** on port 5000 (the same
paths the monolith used, so clients are unchanged). The gateway relays each to
the headless inference-service, the training-service or the `os-base` hardware agent
over gRPC, or fans the MJPEG feeds out of shared memory.

## Detection

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/status` | System state, active model, thresholds, runtime, FPS |
| `POST` | `/api/v1/start` | Start detection |
| `POST` | `/api/v1/stop` | Stop detection |
| `GET` | `/api/v1/stats` | FPS, latency, detection count, frames with detections |
| `POST` | `/api/v1/stats/reset` | Reset the stats counters |
| `GET` | `/api/v1/stats/stream` | Server-Sent Events stream of the stats. Heartbeat (`: keepalive`) every 15s when idle. Used by the Node-RED `stats` node |
| `GET` | `/api/v1/events/stream` | Unified Server-Sent Events stream: invalidation events (each carries a `keys` list to re-fetch) from any client; opt-in `?stats=1` multiplexes the live stats channel onto the same connection. Used by the web app (one connection instead of two) and the Node-RED nodes |
| `GET` | `/api/v1/detections/snapshot` | Latest detections snapshot (JSON); each detection carries its normalized `bbox` corners. `?include_frame=false` omits the annotated JPEG frame; `?include_raw_frame=true` adds the clean frame (`raw_frame`, no overlay — used for dataset ingest). `pending_backlog` reports how many records the offline buffer holds. Polled by the [hub](services/hub-vision.md) over mTLS |
| `GET` | `/api/v1/detections/backlog` | One page of offline-buffered detection records, oldest first (`?limit=N`, default 25, max 100). Each record carries `id`, `captured_at` and the snapshot-format detections/frame; the envelope adds `device_now` (the device clock, so the hub can offset-correct timestamps) and `pending` |
| `POST` | `/api/v1/detections/backlog/ack` | Delete buffered records the hub confirmed persisting — body `{"ids": [..]}`, idempotent. The hub calls this only after its own store insert committed |
| `GET` | `/api/v1/health` | Health check |

## Models

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/models` | List available models (name, size, date, active) |
| `POST` | `/api/v1/model` | Upload a model. `.pt` → async conversion (202 + `job_id`). Other formats load immediately |
| `POST` | `/api/v1/model/select` | Select active model by name |
| `DELETE` | `/api/v1/model/<name>` | Remove a model |
| `GET` | `/api/v1/model/<name>/download` | Download the model file |
| `GET` | `/api/v1/model/conversion` | List active conversion jobs |
| `GET` | `/api/v1/model/conversion/<job_id>` | Conversion status: `pending`, `converting_to_onnx`, `converting_to_engine`, `done`, `failed` |

## Configuration

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/config` | Current configuration (device, resolution, framerate, thresholds) |
| `PUT` | `/api/v1/config` | Update configuration |
| `POST` | `/api/v1/threshold` | Set confidence threshold (0.0–1.0) |
| `POST` | `/api/v1/overlay_threshold` | Set IoU/NMS threshold (0.0–1.0) |

## Camera

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/camera/devices` | List V4L2 devices + current configuration |
| `POST` | `/api/v1/camera/config` | Update camera (index, width, height, framerate) via shared memory |

## Video (MJPEG fanned out of shared memory)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/video_feed` | Raw MJPEG stream (camera SHM ring) |
| `GET` | `/api/v1/video_feed_processed` | MJPEG stream with detection overlays (processed SHM ring) |

## Trigger and counter

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/trigger/status` | Trigger state (`trigger_enabled`) and `detection_count` |
| `POST` | `/api/v1/trigger/enable` | Enables frame processing |
| `POST` | `/api/v1/trigger/disable` | Freezes the last processed frame |
| `GET` | `/api/v1/counter` | Accumulated detection counter |
| `POST` | `/api/v1/counter/reset` | Resets the counter |

## Detection areas

Normalized coordinates in `[0, 1]`; the per-click delta size is controlled by
`AREA_MOVE_DELTA` and `AREA_RESIZE_DELTA` (default `0.02` each). Every
endpoint returns the full state (`{"areas": [...]}`).

| Method | Endpoint | Description |
|---|---|---|
| `GET`    | `/api/v1/detection-areas`               | List every area |
| `POST`   | `/api/v1/detection-areas`               | Create a new area (40%×40%, centered, `is_editing=true`); turns off the previous `editing` flag |
| `DELETE` | `/api/v1/detection-areas/<id>`          | Remove the area |
| `POST`   | `/api/v1/detection-areas/<id>/save`     | Leave editing mode (commit — overlay disappears, filter stays) |
| `POST`   | `/api/v1/detection-areas/<id>/discard`  | Discard pending edits: restore the pre-edit geometry/shape, or remove the area entirely if it was newly created |
| `POST`   | `/api/v1/detection-areas/<id>/edit`     | Promote a saved area back to editing mode |
| `POST`   | `/api/v1/detection-areas/<id>/shape`    | Body `{"shape": "rectangle"\|"circle"}` |
| `POST`   | `/api/v1/detection-areas/<id>/command`  | Body `{"action": "<command>"}`. Commands: `move_up`, `move_down`, `move_left`, `move_right`, `grow`, `shrink`, `grow_horizontal`, `shrink_horizontal`, `grow_vertical`, `shrink_vertical` |

## Classes and system

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/classes` | List labels/classes |
| `POST` | `/api/v1/classes` | Upload `classes.txt` or JSON with a list of names |
| `DELETE` | `/api/v1/classes` | Clear custom classes (revert to the model default) |
| `GET` | `/api/system/status` | CPU%, RAM%, disk%, temperature, GPU% (use/temp/freq — Jetson sysfs) |
| `POST` | `/api/v1/system/power` | Shut down or restart the host. Body `{"action": "shutdown"\|"restart"}` (relayed to the `os-base` hardware agent's `SystemPower` RPC) |

## GPIO and network (relayed to the `os-base` hardware agent)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/gpio/status` | GPIO availability, trigger mode, output pins and their current levels |
| `POST` | `/api/v1/gpio/trigger` | Enable/disable GPIO trigger mode (`{"enabled": bool}`) |
| `POST` | `/api/v1/gpio/pin` | Drive an output pin HIGH/LOW (`{"pin": 29\|31\|33, "level": bool}`). Used by the Node-RED `gpio` node |
| `GET` | `/api/v1/network/config` | Current wired + Wi-Fi configuration |
| `POST` | `/api/v1/network/config` | Apply IPv4 settings (`static`/`auto`) |
| `GET` | `/api/v1/network/wifi/scan` | List available Wi-Fi networks |
| `POST` | `/api/v1/network/wifi/connect` | Connect to a network (`{ssid, password}`) |
| `POST` | `/api/v1/network/wifi/forget` | Remove a saved network (`{ssid}`) |

## Training (relayed to the training-service)

See [training-service](services/training-service.md) for the workflow. Every
dataset-scoped route carries the `dataset_id` explicitly.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/training/enter` | Enter training mode (acquire GPU handover from inference) |
| `POST` | `/api/v1/training/exit` | Leave training mode (resume inference runtime) |
| `GET` | `/api/v1/training/preview` | Capture-preview frame (current camera image) |
| `GET` | `/api/v1/training/datasets` | List datasets (id, name, counts, cover) |
| `POST` | `/api/v1/training/datasets` | Create a dataset |
| `POST` | `/api/v1/training/datasets/upload` | Import a ZIP of a pre-existing YOLO-format dataset |
| `GET` | `/api/v1/training/datasets/<dataset_id>` | Dataset metadata |
| `PUT` | `/api/v1/training/datasets/<dataset_id>` | Rename a dataset |
| `DELETE` | `/api/v1/training/datasets/<dataset_id>` | Delete a dataset |
| `GET` | `/api/v1/training/datasets/<dataset_id>/export` | Export the dataset as a ZIP; `?shards=N&index=I[&seed=S]` exports one deterministic IID shard instead (federated training) |
| `PUT` | `/api/v1/training/datasets/<dataset_id>/cover` | Set the dataset cover image |
| `POST` | `/api/v1/training/datasets/<dataset_id>/capture` | Capture the current camera frame into the dataset |
| `POST` | `/api/v1/training/datasets/<dataset_id>/images` | Add an external image (multipart `file`) with optional pre-labels (`boxes` JSON field: `[{class_name, x1, y1, x2, y2}]`, normalized corners). Letterboxed like a capture; class names are resolved/created. Used by the hub's record-to-dataset flow |
| `GET` | `/api/v1/training/datasets/<dataset_id>/images` | List images (+ label state, replica flag) |
| `GET` | `/api/v1/training/datasets/<dataset_id>/images/<image_id>` | Fetch an image (JPEG) |
| `DELETE` | `/api/v1/training/datasets/<dataset_id>/images/<image_id>` | Delete an image (and its labels) |
| `GET` | `/api/v1/training/datasets/<dataset_id>/images/<image_id>/labels` | Get the image's labels |
| `PUT` | `/api/v1/training/datasets/<dataset_id>/images/<image_id>/labels` | Replace the image's labels |
| `POST` | `/api/v1/training/datasets/<dataset_id>/images/<image_id>/replicate` | Replicate a labeled image (image + labels) N times (1–50) to grow the dataset |
| `GET` | `/api/v1/training/datasets/<dataset_id>/classes` | List dataset classes |
| `POST` | `/api/v1/training/datasets/<dataset_id>/classes` | Add one class (`{"name": ...}`); returns the full class list |
| `PUT` | `/api/v1/training/datasets/<dataset_id>/classes/<index>` | Rename the class at `index` |
| `DELETE` | `/api/v1/training/datasets/<dataset_id>/classes/<index>` | Remove the class at `index` |
| `GET` | `/api/v1/training/sam` | SAM3 worker status (loaded/unloaded) |
| `POST` | `/api/v1/training/sam/load` | Load the SAM3 segmentation worker |
| `POST` | `/api/v1/training/sam/unload` | Unload the SAM3 worker (free GPU memory) |
| `POST` | `/api/v1/training/sam/segment` | SAM3-assisted segmentation for a prompt |
| `POST` | `/api/v1/training/train` | Start a training job. Federated round: `{"federated": true, "initial_weights_id": ...}` trains from a stashed checkpoint and retains the resulting `last.pt` (`model_name` optional) |
| `GET` | `/api/v1/training/train/status` | Current job status / progress (federated jobs expose `result_weights_id` when done) |
| `POST` | `/api/v1/training/train/cancel` | Cancel the running job |
| `POST` | `/api/v1/training/train/finish` | Finish: hand `best.pt` to the model-upload route (pt→onnx→engine) |
| `POST` | `/api/v1/training/weights` | Stash a checkpoint (multipart `file`) for federated training; returns `{"weights_id", "size"}` |
| `GET` | `/api/v1/training/weights/<weights_id>` | Download a stashed checkpoint (`.pt` blob) |
| `DELETE` | `/api/v1/training/weights/<weights_id>` | Delete a stashed checkpoint (TTL prune is the backstop) |
| `POST` | `/api/v1/training/weights/average` | FedAvg: average ≥2 stashed checkpoints (`{"weights_ids": [...]}`) into a new one (CPU child process) |

## Enrollment (device pairing)

Served under `/enroll/*` and used by the [hub](services/hub-vision.md) to pair
a device. Before pairing, nginx serves these routes over a self-signed cert;
once enrolled it flips to mTLS-enforcing mode automatically. Pairing needs no
token by default (first hub on the trusted LAN wins); set `DEVICE_PAIR_TOKEN`
to require a shared secret.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/enroll/info` | Public pairing info: `device_id`, `logical_name`, `enrolled`, `token_required`, `key_fingerprint` |
| `POST` | `/enroll/csr` | Return a CSR for the hub to sign (authorized per the pairing policy) |
| `POST` | `/enroll/complete` | Install the hub-signed `device_cert` + `ca_cert`; nginx reloads into mTLS-enforcing mode |
| `POST` | `/enroll/reset` | Unpair: clear the cert + CA and return to enrollment mode. Requires the owning hub (mTLS) or the pairing token |

## Legacy aliases

Simplified `/api/*` aliases kept for older clients; each relays to its
`/api/v1/*` counterpart above.

| Method | Endpoint | Alias of |
|---|---|---|
| `GET` | `/api/status` | `/api/v1/status` |
| `POST` | `/api/start` | `/api/v1/start` |
| `POST` | `/api/stop` | `/api/v1/stop` |
| `POST` | `/api/threshold` | `/api/v1/threshold` |
| `POST` | `/api/overlay_threshold` | `/api/v1/overlay_threshold` |
| `GET` | `/api/models` | `/api/v1/models` (returns the bare model list) |
| `GET` | `/api/health` | `/api/v1/health` |
| `GET` | `/api/classes` | `/api/v1/classes` |
| `POST` | `/api/classes` | `/api/v1/classes` |
