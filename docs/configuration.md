# Configuration

Environment variables read by each service. **Default** is the value built into
the code (what applies when the variable is unset); where the production
`docker-compose.yml` sets a different value, the **Compose** column shows it.

## `webcam-server`

| Variable | Default | Compose | Description |
|---|---|---|---|
| `CAMERA_INDEX` | `0` | — | Camera device index |
| `CAPTURE_WIDTH` | `2560` | — | Capture width |
| `CAPTURE_HEIGHT` | `720` | — | Capture height |
| `CAPTURE_FRAMERATE` | `60` | — | Capture FPS |
| `SHM_NAME` | `conecsa_frame_shm` | — | Shared memory segment name |
| `SHM_SLOT_MIN_BYTES` | `8388608` (8 MB) | `16777216` (16 MB) | Minimum SHM slot size — must fit the largest possible frame; compose raises it so the stereo camera's native 3840×1080 RAW fallback (12.44 MB/frame) fits |

## `inference-service`

| Variable | Default | Compose | Description |
|---|---|---|---|
| `SHM_NAME` | `conecsa_frame_shm` | — | Camera SHM segment name (must match webcam-server) |
| `INFERENCE_GRPC_LISTEN` | `0.0.0.0:50061` | — | gRPC control server bind address |
| `PROCESSING_DECODE_SCALE` | `1` | — | Reduced-scale JPEG decode for inference/overlay (1 = full, 2 = half, 4 = quarter). Must stay `1` for the default tiled inference (`TILING_MODE=grid`) and for models trained above 640; `2` is the cheaper choice only with `TILING_MODE=off` and a 640 model trained on whole frames |
| `PROCESSED_OUTPUT_SCALE` | `1` | — | Downscale factor (`1`, `2`, `4`) applied to the drawn frame before JPEG encoding/publishing; keeps the single-thread encode stage and the MJPEG stream small when the decode scale is `1` |
| `INFER_LETTERBOX_PAD` | `0` | — | Letterbox pad value (0–255) for the model input; training letterboxes with `114` |
| `INFER_RESIZE_INTERP` | `nearest` | — | Resize interpolation for the model input (`nearest`, `linear`, `area`); training uses linear |
| `TILING_MODE` | `grid` | — | SAHI-style tiled inference. `grid` (default) slices the decoded frame into overlapping square tiles, runs one inference per tile and merges the shifted boxes, so small objects reach the model near native scale; `off` keeps the single full-frame letterboxed inference for models trained on whole frames. A model only performs at the geometry it was trained at: pair `grid` with a model trained by the training-service's default `TRAIN_TILE=auto` (the model's settings sidecar records its geometry and activation logs a warning on a mismatch). Requires `PROCESSING_DECODE_SCALE=1` so tiles are cut from native pixels |
| `TILING_TILE` | `auto` | — | Square tile side for `TILING_MODE=grid`: `auto` = the frame's short side, resolved per frame, so any 16:9 camera gives two columns (K=2) whatever its resolution (measured on a 1280×720 frame: two 720 px tiles); a pixel value pins the side and must then match the `TRAIN_TILE` the model was trained with |
| `TILING_OVERLAP` | `0.2` | — | Fraction of `TILING_TILE` that adjacent tiles overlap (`0 ≤ f < 1`); the band must exceed the largest object the tiles are meant to catch |
| `TILING_MERGE_IOU` | `0.5` | — | IoU above which boxes from different tiles are merged as one object (class-aware greedy NMS, `conecsa_common.tiling.merge_tiles`) |
| `STEREO_COMBINE` | `none` | `none` | Stereo combine mode — split the side-by-side frame and blend both eyes into one image. Starts off: it would tear an ordinary camera's picture in half, so the Camera Settings toggle (shown only for a 3D camera) enables it and the per-model settings snapshot restores it |
| `STEREO_BLEND_ALPHA` | `0.5` | — | Blend factor for `STEREO_COMBINE=blend` |
| `CAPTURE_AUTO_EXPOSURE` | `false` | — | Camera auto-exposure |
| `CAPTURE_EXPOSURE_TIME` | `10000 / framerate` | `166` | Manual exposure time |
| `CAPTURE_RGB_RED` / `_GREEN` / `_BLUE` | `128` | — | Per-channel white-balance gains |
| `CAPTURE_GAMMA` | `100` | — | Camera gamma |
| `CAPTURE_GAIN` | `0` | — | Camera gain |
| `TENSORRT_WORKSPACE_MB` | `256` | `192` | TensorRT builder workspace (MB) for `.pt → .engine` conversion; 1280 engines usually need `512` (the builder retries 256/192/128) |
| `TENSORRT_AUTO_REBUILD_ENGINE` | `1` | — | Rebuilds the engine when the model changes |
| `TENSORRT_CONTEXTS` | `1` | `2` | Parallel TensorRT contexts / pipeline lanes (~1.8× GPU scaling at 2) |
| `CUDA_VISIBLE_DEVICES` | `0` | — | GPU visible to CUDA |
| `HUB_OFFLINE_THRESHOLD_SEC` | `5.0` | — | Seconds without a hub snapshot poll before the device considers the hub offline and starts buffering detections |
| `DETECTION_BUFFER_MAX_RECORDS` | `5000` | — | Offline detection buffer cap (records); oldest evicted first |
| `DETECTION_BUFFER_MAX_BYTES` | `1073741824` (1 GB) | — | Offline detection buffer cap (bytes); whichever cap hits first evicts |
| `DETECTIONS_DIR` | `/data/detections` | — | Offline buffer directory (`buffer.db`); falls back to a repo-local dir on host runs |

## `api-gateway`

| Variable | Default | Compose | Description |
|---|---|---|---|
| `INFERENCE_GRPC_ADDR` | `inference-service:50061` | — | Headless inference gRPC control surface |
| `TRAINING_GRPC_ADDR` | `training-service:50071` | — | Training-service gRPC control surface |
| `HARDWARE_AGENT_ADDR` | `os:50051` | `os-base:50051` | `os-base` hardware agent (network/Wi-Fi/GPIO) — compose uses the `os-base` service name |
| `SHM_NAME` | `conecsa_frame_shm` | — | Camera SHM ring (raw feed) |
| `PROCESSED_SHM_NAME` | `conecsa_processed_shm` | — | Processed SHM ring (overlaid feed) |
| `GATEWAY_PORT` | `5000` | — | Internal HTTP port |
| `WAITRESS_THREADS` | `32` | — | Waitress task threads (MJPEG/SSE pin one each) |
| `STEREO_COMBINE` | `none` | `none` | Stereo combine for the training preview (matches inference-service); fallback only — the live inference config wins when reachable |
| `STEREO_BLEND_ALPHA` | `0.5` | — | Blend factor for the training preview |
| `DEVICE_VERSION` | _(empty)_ | `2026.4-LTS` | Device software version, surfaced on `/api/v1/status` + `/api/v1/health` for the hub |
| `DEVICE_ID` | _(host hostname)_ | — | Device identity used by enrollment, the cert SAN and mDNS |
| `CONECSA_CERT_DIR` | `/etc/conecsa/certs` | — | Device key/CSR + hub-signed cert/CA (volume shared with the nginx TLS terminator) |
| `DEVICE_PAIR_TOKEN` | _(unset)_ | `${DEVICE_PAIR_TOKEN:-}` | Optional shared pairing secret; unset = first hub on the trusted LAN to pair wins |
| `HUB_MDNS_ENABLED` | `1` | `0` | In-container mDNS advertiser; disabled in production (the host avahi-daemon advertises instead) |
| `CLOCK_SYNC_THRESHOLD_SEC` | `30` | — | Drift from the hub's clock that triggers a step (the board has no RTC battery; see [Clock synchronization](services/hub-vision.md#clock-synchronization)) |
| `CLOCK_SYNC_MIN_INTERVAL_SEC` | `60` | — | Minimum spacing between clock-step attempts, so a failing step is not retried on every 2s hub poll |
| `AUDIT_DIR` | `/data/audit` | `/data/audit` | Audit trail directory (`audit.db`); needs a writable volume (`conecsa-audit-data`) |
| `AUDIT_MAX_RECORDS` | `50000` | — | Audit ring cap (records); oldest evicted first |
| `AUDIT_MAX_BYTES` | `67108864` (64 MB) | — | Audit ring cap (bytes); whichever cap hits first evicts |

## `training-service`

| Variable | Default | Compose | Description |
|---|---|---|---|
| `SHM_NAME` | `conecsa_frame_shm` | — | Camera SHM ring (capture source; must match webcam-server) |
| `STEREO_COMBINE` | `none` | `none` | Stereo combine mode — compose sets inference-service to the same value so captured images match the live detector geometry (there is no runtime sync; the live inference config wins when reachable) |
| `STEREO_BLEND_ALPHA` | `0.5` | — | Blend factor for `STEREO_COMBINE=blend` |
| `GATEWAY_ADDR` | `http://api-gateway:5000` | — | Gateway URL used to hand `best.pt` back through the model-upload route |
| `TRAIN_IMG_SIZE` | `640` | — | Model input size (`imgsz`) for training and for the exported ONNX/engine. 640 is the production default (a plain 1280 engine runs well below the live-pipeline fps floor on the Orin Nano); larger values train on real pixels only because datasets are stored at native resolution |
| `TRAIN_DATASET_IMG_SIZE` | `0` | `0` | Dataset storage geometry. `0` (default) stores the stereo-combined camera frame at native resolution and leaves letterboxing to ultralytics at train time; a value > 0 reproduces the legacy format (images letterboxed to that square, historically `640`). Recorded per dataset in `meta.json`; adding images to a dataset created with a different geometry is refused |
| `TRAIN_TILE` | `auto` | — | Training geometry. `auto` (default) slices every image of the train/valid split into the square tile crops the inference-service runs on — side = the image's short side, the same `conecsa_common.tiling` grid as `TILING_TILE=auto` — and rewrites the labels per tile, so the model is trained at the scale it is deployed at; a pixel value mirrors an explicit `TILING_TILE`; `off` trains on whole frames for a device running `TILING_MODE=off`. Images the grid cannot slice (a legacy 640×640 letterboxed dataset) stay whole. The effective geometry (`frames`, `tiles:auto`, `tiles:<px>`) is declared on the model upload and recorded in the model's settings sidecar |
| `TRAIN_TILE_OVERLAP` | `0.2` | — | Overlap fraction between adjacent training tiles (`0 ≤ f < 1`); mirrors `TILING_OVERLAP` |
| `TRAIN_TILE_MIN_VISIBLE` | `0.25` | — | A box is kept in a tile when at least this fraction of its area lies inside it (`0 < f ≤ 1`); a tile whose only content was a smaller fragment is skipped rather than taught as background |
| `TRAIN_OVERRIDES` | _(empty)_ | — | Space-separated allowlisted ultralytics `model.train` hyperparameters, e.g. `freeze=10 lr0=0.002 close_mosaic=5` (allowlist in `training-service/service/train_overrides.py`) |
| `TRAIN_BATCH` | `4` | — | YOLO training batch size (sized for the Orin Nano 8 GB) |
| `TRAIN_WORKERS` | `0` | — | DataLoader workers (0 = single-process; the small shared `/dev/shm` cannot back worker tensors) |
| `TRAIN_STALL_TIMEOUT_SEC` | `3600` | — | Liveness watchdog — kills the trainer after this long with **no** output (a hang), not a cap on total duration |
| `TRAIN_TIMEOUT_SEC` | _(unset)_ | — | Optional overall wall-clock cap on a training run |
| `TRAINING_MAX_WEIGHTS_MB` | `200` | — | Cap per uploaded federated checkpoint (`last.pt` carries optimizer state, ~2-3× the model size) |
| `TRAINING_WEIGHTS_TTL_SEC` | `86400` | — | TTL of stashed federated checkpoints under `{DATA_DIR}/weights/` (hub deletes best-effort; the prune is the backstop) |
| `SAM3_CHECKPOINT` | `/app/training-service/assets/sam3.pt` | — | SAM3 checkpoint (HF-gated; downloaded locally and baked into the image at build time) |

## `system-vision`

| Variable | Default | Compose | Description |
|---|---|---|---|
| `SYSTEM_VISION_TLS_PORT` | `443` | — | Published mTLS port — the **only** port the production stack exposes |
| `SYSTEM_VISION_PORT` | `80` | _(dev only)_ | Plaintext web port; used only by `docker-compose.dev.yml`, never published in production |
| `API_BASE_URL` | `http://api-gateway:5000` | — | API URL (legacy; the WASM frontend resolves it at runtime from the browser host via `get_api_base_url()`, so this is unused for the web build) |

## `flow`

| Variable | Default | Compose | Description |
|---|---|---|---|
| `INFERENCE_URL` | `http://api-gateway:5000` | — | Base URL the Conecsa nodes use to reach the api-gateway |
| `DEVICE_ID` | _(empty)_ | — | Device id stamped on detection messages (node config takes precedence) |
| `TZ` | — | `America/Sao_Paulo` | Timezone |

> The Flow editor's port (`1880`) is published only by the dev stack
> (`docker-compose.dev.yml`); in production it is reachable through the
> hub's mTLS proxy.
