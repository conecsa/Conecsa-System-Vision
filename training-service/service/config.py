"""Environment-driven configuration for the training-service."""
import os
from typing import Optional, Union

TileSpec = Union[None, str, int]
"""Training tile knob: ``None`` = whole frames, ``"auto"`` = the image's short side, ``int`` = px."""


def parse_train_tile(raw: Optional[str]) -> TileSpec:
    """Normalise ``TRAIN_TILE``: ``auto`` (default) | ``off``/``0`` | ``<px>``.

    Anything unparseable falls back to ``auto`` rather than silently
    disabling the crop — the product default is the tiled geometry.
    """
    value = (raw or "").strip().lower()
    if value in ("off", "0", "none", "false", "no"):
        return None
    if value in ("", "auto"):
        return "auto"
    try:
        pixels = int(value)
    except ValueError:
        return "auto"
    return pixels if pixels > 0 else "auto"


def _env_fraction(name: str, default: float, *, low_inclusive: bool, high_inclusive: bool) -> float:
    """A float env var restricted to the unit interval; out of range ⇒ *default*."""
    value = _env_float(name, default)
    above_low = value >= 0.0 if low_inclusive else value > 0.0
    below_high = value <= 1.0 if high_inclusive else value < 1.0
    return value if above_low and below_high else default


def _env_float(name: str, default: float) -> float:
    """Read an environment variable as a float, falling back to *default*."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    """Read an environment variable as an int, falling back to *default*."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Config:
    """Environment-driven training-service configuration (paths, GPU, training knobs)."""

    # gRPC control surface
    GRPC_LISTEN = os.environ.get("TRAINING_GRPC_LISTEN", "0.0.0.0:50071")

    # Camera SHM ring (shared ipc namespace with webcam-server)
    SHM_NAME = os.environ.get("SHM_NAME", "conecsa_frame_shm")

    # Stereo combine — same defaults as the inference-service so captured
    # dataset images match the geometry the live detector sees.
    STEREO_COMBINE = os.environ.get("STEREO_COMBINE", "none").strip().lower()
    STEREO_BLEND_ALPHA = min(max(_env_float("STEREO_BLEND_ALPHA", 0.5), 0.0), 1.0)
    STEREO_OFFSET = min(max(_env_float("STEREO_OFFSET", 0.0), -0.5), 0.5)
    STEREO_OFFSET_Y = min(max(_env_float("STEREO_OFFSET_Y", 0.0), -0.5), 0.5)

    # Dataset / runs storage (named volume)
    DATA_DIR = os.environ.get("TRAINING_DATA_DIR", "/data/training")

    # Cap for an uploaded dataset ZIP (spooled file AND uncompressed total).
    MAX_DATASET_UPLOAD_MB = _env_int("TRAINING_MAX_UPLOAD_MB", 512)

    # Federated weights stash: cap per uploaded checkpoint (last.pt carries
    # optimizer state, ~2-3x the model size) and how long stashed blobs live
    # before pruning — the hub deletes round-scoped blobs best-effort, the TTL
    # is the backstop.
    MAX_WEIGHTS_UPLOAD_MB = _env_int("TRAINING_MAX_WEIGHTS_MB", 200)
    WEIGHTS_TTL_SEC = _env_int("TRAINING_WEIGHTS_TTL_SEC", 86400)

    # Training defaults (sized for the Jetson Orin Nano 8GB)
    # Model input size passed to the trainer (``--imgsz``) and to the .pt upload
    # so the exported ONNX/engine matches the trained resolution. 640 is the
    # production default; larger values need a native-resolution dataset.
    IMG_SIZE = _env_int("TRAIN_IMG_SIZE", 640)
    # Dataset storage geometry. 0 (the default) stores the
    # stereo-combined frame at its native resolution and leaves letterboxing to
    # ultralytics at train time — real pixels for any imgsz, and a single
    # dataset serves any imgsz and the tile crops alike. A value > 0 reproduces
    # the legacy format: images letterboxed to that square (640) on
    # capture/import/hub ingest. Recorded per dataset in meta.json so
    # geometries are never mixed inside one dataset.
    DATASET_IMG_SIZE = _env_int("TRAIN_DATASET_IMG_SIZE", 0)
    # Extra ultralytics ``model.train`` hyperparameters (space-separated
    # ``key=value``, allowlisted in service/train_overrides.py), e.g.
    # ``freeze=10 lr0=0.002 close_mosaic=5``. Empty = ultralytics defaults.
    TRAIN_OVERRIDES = os.environ.get("TRAIN_OVERRIDES", "")
    # Training geometry. The inference-service slices every frame into square
    # tiles (TILING_MODE=grid, tile side = the frame's short side by default)
    # and a model only performs at the scale it was trained at, so the split
    # builder crops each dataset image with the same grid
    # (conecsa_common.tiling) and rewrites the labels per tile. ``auto``
    # (default) mirrors the inference default on any camera resolution; a
    # pixel value mirrors an explicit TILING_TILE; ``off`` trains on whole
    # frames for a device running TILING_MODE=off. Overlap mirrors
    # TILING_OVERLAP; a box survives in a tile when at least MIN_VISIBLE of
    # its area lies inside it.
    TRAIN_TILE: TileSpec = parse_train_tile(os.environ.get("TRAIN_TILE", "auto"))
    TRAIN_TILE_OVERLAP = _env_fraction("TRAIN_TILE_OVERLAP", 0.2,
                                       low_inclusive=True, high_inclusive=False)
    TRAIN_TILE_MIN_VISIBLE = _env_fraction("TRAIN_TILE_MIN_VISIBLE", 0.25,
                                           low_inclusive=False, high_inclusive=True)
    MIN_IMAGES = _env_int("TRAIN_MIN_IMAGES", 20)
    DEFAULT_EPOCHS = _env_int("TRAIN_DEFAULT_EPOCHS", 50)
    DEFAULT_PATIENCE = _env_int("TRAIN_DEFAULT_PATIENCE", 50)
    TRAIN_BATCH = _env_int("TRAIN_BATCH", 4)
    # 0 = single-process data loading. The container shares webcam-server's
    # small /dev/shm (ipc: service:webcam-server), which DataLoader workers
    # exhaust; single-process loading is trivial for the small datasets here.
    TRAIN_WORKERS = _env_int("TRAIN_WORKERS", 0)
    TRAIN_AMP = os.environ.get("TRAIN_AMP", "1") not in ("0", "false", "no")
    # Overall wall-clock cap; 0 disables it. Large datasets / many epochs can
    # legitimately run for many hours, so hangs are caught by the stall
    # watchdog below instead of a hard cap.
    TRAIN_TIMEOUT_SEC = _env_int("TRAIN_TIMEOUT_SEC", 0)
    # Liveness watchdog: kill the trainer when it produces NO output (stdout
    # epoch lines or stderr logs) for this long. Ultralytics prints at least
    # once per epoch, so this must exceed the slowest plausible epoch.
    TRAIN_STALL_TIMEOUT_SEC = _env_int("TRAIN_STALL_TIMEOUT_SEC", 3600)
    BASE_WEIGHTS = os.environ.get("TRAIN_BASE_WEIGHTS", "/app/training-service/assets/yolo26s.pt")

    # Where finished models go (the gateway relays to the inference-service,
    # which owns conversion + activation).
    GATEWAY_ADDR = os.environ.get("GATEWAY_ADDR", "http://api-gateway:5000")

    # SAM3 assisted labeling. The checkpoint is baked into the image at build
    # time (training-service/assets/, gitignored — the operator downloads the
    # HF-gated file locally before building). Point the env at a volume path
    # instead to swap checkpoints without a rebuild.
    SAM3_CHECKPOINT = os.environ.get(
        "SAM3_CHECKPOINT", "/app/training-service/assets/sam3.pt"
    )
    SAM_WORKER_PORT = _env_int("SAM_WORKER_PORT", 5601)
    SAM_IDLE_UNLOAD_SEC = _env_int("SAM_IDLE_UNLOAD_SEC", 300)

    @property
    def datasets_dir(self) -> str:
        return os.path.join(self.DATA_DIR, "datasets")

    @property
    def legacy_dataset_dir(self) -> str:
        # Pre-multi-dataset layout; migrated into datasets_dir on startup.
        return os.path.join(self.DATA_DIR, "dataset")

    @property
    def runs_dir(self) -> str:
        return os.path.join(self.DATA_DIR, "runs")

    @property
    def weights_dir(self) -> str:
        return os.path.join(self.DATA_DIR, "weights")
