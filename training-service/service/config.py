"""Environment-driven configuration for the training-service."""
import os


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
    STEREO_COMBINE = os.environ.get("STEREO_COMBINE", "blend").strip().lower()
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
    IMG_SIZE = 640
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
