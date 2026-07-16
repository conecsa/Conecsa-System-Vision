# Training Service (Python, headless)

On-device dataset capture, SAM3-assisted labeling and YOLO training. Like the
inference-service it is **headless**: the only surface is a **gRPC control
server** on `:50071` (`proto/training.proto`, `TrainingControl`), wired at
module load (`composition.Application`), after which the process blocks. The
api-gateway owns all HTTP/SSE — there is no Flask here. Heavy work (torch /
ultralytics / SAM3) always runs in **child processes**; this service is only the
control plane.

## Responsibilities

- **Datasets** — multiple datasets live under
  `{DATA_DIR}/datasets/{dataset_id}/` (camera captures + YOLO labels + classes).
  Every dataset-scoped RPC carries the `dataset_id` explicitly; the server keeps
  no "active dataset" state. Datasets can also be imported from / exported to a
  ZIP of a standard YOLO layout (`images/` + `labels/` + `data.yaml`).
- **Capture** — captures the current camera frame (read from the camera SHM
  ring) into a dataset. The compose file sets `STEREO_COMBINE` /
  `STEREO_BLEND_ALPHA` to the same values on this service and the
  inference-service so captured images match the geometry the live detector
  sees (there is no runtime sync — and the code defaults differ when unset:
  `blend` here vs `none` in the inference-service).
- **Replicate** — duplicates a labeled image (the JPEG plus its YOLO labels)
  1–50 times to quickly reach the training minimum (`TRAIN_MIN_IMAGES`, 20).
  Replicas are flagged in `meta.json` (`replica_image_ids`) so the gallery can
  mark them; an unlabeled source or an already-replicated image is rejected.
- **Pre-labeled ingest** (`AddDatasetImage`) — accepts an externally captured
  image plus pre-labels carried by **class name** with normalized corner
  coordinates on the uploaded image. The JPEG is letterboxed to 640×640 like a
  camera capture, the coordinates are mapped into the letterbox space
  (`corners_to_letterbox` mirrors `letterbox_square`'s exact rounding), and
  class names are resolved against `classes.json` — missing names are
  appended — so the image arrives already labeled. This is how the hub feeds a
  detection record's clean frame back into a dataset for retraining; the
  operator only adjusts the class in the label editor when the model got it
  wrong.
- **SAM3-assisted labeling** — an on-demand SAM3 worker
  (`SAM3_CHECKPOINT`, HF-gated and baked into the image at build time) turns a
  user prompt into a segmentation/box, loaded and unloaded explicitly to free
  GPU memory.
- **Training job** — one ultralytics run at a time, executed in a child process
  (`_yolo_trainer`) that streams one JSON line per epoch; a reader thread folds
  those into the job state and publishes `training_progress` events. On success
  the resulting `best.pt` is uploaded through the api-gateway's existing
  model-upload route, which renames it to the user-chosen model name and starts
  the `pt → onnx → engine` conversion on the inference-service — the same path a
  manual upload takes.

## Federated training (hub-orchestrated FedAvg)

The [hub](hub-vision.md) can train one model across every paired device
without any device-to-device traffic: it ferries opaque `.pt` blobs over its
per-device mTLS channel. The service-side building blocks:

- **Shard export** — `ExportDatasetShard` exports one deterministic IID shard
  of a dataset (shuffle by a shared seed + round-robin assignment): the N
  shards of one seed are disjoint, cover the full dataset and differ in size
  by at most one image. `data.yaml` always carries the full class list so
  per-shard checkpoints stay averageable.
- **Weights stash** — opaque checkpoints under `{DATA_DIR}/weights/{id}.pt`
  (`UploadWeights` / `DownloadWeights` / `DeleteWeights`), capped by
  `TRAINING_MAX_WEIGHTS_MB` and pruned after `TRAINING_WEIGHTS_TTL_SEC`.
- **Federated train mode** — `TrainRequest.federated` starts the regular job
  from a stashed checkpoint (`initial_weights_id`, falling back to the baked-in
  base weights) and, on success, stashes the resulting **`last.pt`** (same
  number of local epochs on every device) as `result_weights_id` instead of
  uploading a model.
- **Averaging** — `AverageWeights` FedAvg-merges ≥2 stashed checkpoints in a
  CPU child process (`_weights_averager`, same isolation rule as the trainer):
  float tensors of the `model` **and** `ema` state dicts averaged in fp32 and
  cast back, non-float buffers kept from the first checkpoint, optimizer state
  dropped. CPU-only, so it never competes with a GPU training job.

## GPU handover

Training and inference share a single Jetson GPU. Entering training mode hands
the GPU over from the inference runtime (`Release` / `ResumeRuntime` on the
inference-service), and exiting resumes it. The gateway exposes this as
`/api/v1/training/enter` and `/api/v1/training/exit`.

!!! note "Sizing for the Orin Nano 8 GB"
    `TRAIN_BATCH` defaults to 4 and `TRAIN_WORKERS` to 0 (single-process
    DataLoader — the small shared `/dev/shm` from webcam-server's IPC namespace
    cannot back worker tensors). `TRAIN_STALL_TIMEOUT_SEC` is a liveness
    watchdog (kills a *hung* trainer with no output), not a cap on total
    duration; set `TRAIN_TIMEOUT_SEC` for an overall wall-clock cap.

## Reference

- Workflow endpoints: [HTTP API reference — Training](../api-reference.md#training-relayed-to-the-training-service)
- Python API: [`service` package](../reference/python-api/index.md)
- gRPC contract: [`proto/training.proto`](../reference/proto.md)
- Configuration: [training-service env vars](../configuration.md#training-service)
