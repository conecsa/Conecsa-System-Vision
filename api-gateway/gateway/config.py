"""Gateway configuration — all knobs come from the environment.

The gateway holds no business config; it only needs to know where its peers are
(inference gRPC, os hardware agent) and which SHM segments carry the frames.
"""
import os


def _env_float(name: str, default: float) -> float:
    """Read an environment variable as a float, falling back to *default*."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    """Environment-driven gateway configuration (gRPC peers, SHM names, ports)."""

    # gRPC peers (docker-compose service names + <SVC>_ADDR convention).
    INFERENCE_GRPC_ADDR = os.environ.get("INFERENCE_GRPC_ADDR", "inference-service:50061")
    HARDWARE_AGENT_ADDR = os.environ.get("HARDWARE_AGENT_ADDR", "os:50051")
    TRAINING_GRPC_ADDR = os.environ.get("TRAINING_GRPC_ADDR", "training-service:50071")

    # Stereo combine parameters for the training preview (same defaults as the
    # inference-service so the preview matches what gets captured/detected).
    STEREO_COMBINE = os.environ.get("STEREO_COMBINE", "blend").strip().lower()
    STEREO_BLEND_ALPHA = _env_float("STEREO_BLEND_ALPHA", 0.5)
    STEREO_OFFSET = _env_float("STEREO_OFFSET", 0.0)
    STEREO_OFFSET_Y = _env_float("STEREO_OFFSET_Y", 0.0)

    # POSIX SHM rings (shared via the `ipc:` namespace with webcam-server +
    # inference-service). Camera ring is produced by the Rust webcam-server;
    # the processed ring is produced by inference-service's pipeline (Stage D).
    CAMERA_SHM_NAME = os.environ.get("SHM_NAME", "conecsa_frame_shm")
    PROCESSED_SHM_NAME = os.environ.get("PROCESSED_SHM_NAME", "conecsa_processed_shm")

    # HTTP server.
    PORT = int(os.environ.get("GATEWAY_PORT", "5000"))
    WAITRESS_THREADS = int(os.environ.get("WAITRESS_THREADS", "32"))

    # Per-call gRPC deadlines (seconds). Control calls are quick; Wi-Fi
    # scan/connect block on the radio and are given longer in the hardware client.
    GRPC_TIMEOUT = float(os.environ.get("GATEWAY_GRPC_TIMEOUT", "12"))

    # Auto-exit training mode after this much client silence (the orphaned-
    # training watchdog; see gateway/training/orphan.py). 0 disables it.
    # The device UI heartbeats every 10s while the training page is mounted
    # (/training/heartbeat) and the hub coordinator polls every ~2s, so 120s
    # means ~12 missed beats; worst-case fire latency is timeout + the 30s
    # watchdog tick. Kept above 90s so a single long request (multi-GB dataset
    # upload/export touches the tracker only at request start) does not trip it.
    TRAINING_ORPHAN_TIMEOUT_SEC = float(
        os.environ.get("TRAINING_ORPHAN_TIMEOUT_SEC", "120"))


settings = Settings()
