# Inference Service (Python, headless)

No HTTP server — the only surface is a **gRPC control server** on `:50061`
(`proto/inference.proto`: `DetectionControl`, `ModelControl`,
`ManagementControl`), started alongside the decode∥infer∥encode pipeline at
module load; the process then blocks. The pipeline reads the camera SHM ring,
runs inference and publishes the overlaid JPEGs to the processed SHM ring. The
active runtime is TensorRT:

| Runtime | Class | Format | Notes |
|---|---|---|---|
| `TensorRT` | `TensorRTRuntime` | `.pt` /`.engine` / `.plan` / `.onnx` | CUDA 12.6, JetPack 6.2.2 |

`TensorRTRuntime` only handles backend registration and availability; each
loaded model gets its own `TensorRTInterpreter` (a separate module) that owns
the engine, execution context and CUDA buffers and exposes the small
interpreter surface `ModelManager` uses.

The `TFLite`, `LiteRT` and `PyTorch` runtimes have been removed from the code.

Uploads of `.pt` files trigger an asynchronous `.pt → .onnx → .engine`
conversion. The frontend polls `/api/v1/model/conversion/<job_id>`. Accepted
formats: `.engine`, `.plan`, `.pt`, `.onnx`.

On startup, a daemon thread pre-warms the TensorRT worker to eliminate the
cold-start (~30s) on first use.

**Frames via SHM**: a `ShmConsumer` reads the camera ring on a background
thread; camera configuration (resolution, framerate, exposure) is exchanged
back through the same segment, with no HTTP to the webcam-server. The
pipeline's encode stage publishes the processed JPEGs to the **processed SHM
ring** for the api-gateway to fan out.

**Detection areas**: `DetectionAreaService`
(`api/services/detection_area_service.py`) keeps a persistent list of areas
of interest **scoped per-model**: each model's areas live in a sibling file
next to its weights (`weights.engine` → `weights.areas.json`, resolved by
`ModelService.areas_file_for_model()`), so switching models switches area
sets. Each area is a rectangle or
circle with normalized coordinates in `[0,1]` — surviving camera resolution
changes. When at least one area is saved, `YOLODetector` filters detections
whose center falls outside the union of the areas (bbox test for rectangles,
ellipse equation for circles). Areas in *editing* mode do not filter
anything; they only show the overlay (dashed border + dimming alpha=0.4
outside the union) so the user can position them before saving. Saved areas
affect inference but are invisible in the stream. Persistence uses atomic
writes (`tempfile.NamedTemporaryFile` + `os.replace`).

The decode∥infer∥encode pipeline runs decode, inference and encode on separate
threads connected by bounded queues, with a `TENSORRT_CONTEXTS` knob that adds
parallel TensorRT contexts / pipeline lanes (~1.8× GPU scaling at 2). See the
module docstring of `api/services/processing_pipeline.py` for the threading
model.

**Detections snapshot**: `DetectionService.detections_snapshot()` backs the
`Snapshot` RPC and `/api/v1/detections/snapshot`. Each detection carries its
normalized `bbox` corners (`[x1, y1, x2, y2]`, 0..1), and besides the
annotated `frame` (kept as-is — Node-RED flows consume it) the snapshot can
include the **clean** frame (`include_raw_frame` → `raw_frame`): the pristine
image the boxes were detected on, which the hub stores so detection records
can be re-labeled and fed back into a training dataset. The clean frame is
held on `DetectionResult.raw_image` by reference — every pipeline frame is a
freshly allocated buffer and the detector draws on a copy, so this costs
nothing per frame.

**Offline detection buffer (store-and-forward)**: the hub's snapshot poll
(~1×/s) doubles as a hub-is-online heartbeat. Only pulls that arrive through
the mTLS terminator count (the gateway marks them `hub_pull` from the
`X-Conecsa-Client-Verify` header nginx stamps on `:443` traffic, and only
honors that header when the TCP peer is the terminator container itself, so
another container cannot forge it) — local snapshot consumers such as the
Flow detection node poll the same endpoint and must not make the device
believe the hub is online. When no hub poll
arrives for
`HUB_OFFLINE_THRESHOLD_SEC` (default 5s), `DetectionBufferService`
(`api/services/detection_buffer.py`) persists on-change detection records —
same class@area change signature the hub collector uses — to a SQLite ring
buffer at `/data/detections/buffer.db` (the `conecsa-detections-data` volume,
so records survive container restarts and device reboots). Each record stores
the detection list, `captured_at`, and the clean JPEG frame as a BLOB; caps
are 5 000 records / 1 GB (oldest evicted first, discards logged). The snapshot
advertises the row count as `pending_backlog`; the hub drains it via the
`ListBacklog`/`AckBacklog` RPCs (`GET /api/v1/detections/backlog` +
`POST /api/v1/detections/backlog/ack` through the gateway) and rows are
deleted **only after the hub acks having persisted them**. A persisted
`hub_seen` flag keeps a standalone device (never paired) from ever writing,
and buffering is offline-only by design — zero eMMC writes while the hub is
polling. Database errors never take the pipeline down: the buffer recreates a
corrupt file and disables itself as a last resort.

## Reference

- Python API: [`api` package](../reference/python-api/index.md)
- gRPC contract: [`proto/inference.proto`](../reference/proto.md)
- Configuration: [inference-service env vars](../configuration.md#inference-service)
