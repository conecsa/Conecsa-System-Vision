"""Per-frame media fan-out — POSIX SHM, never gRPC.

Two rings, both shared with the gateway via the `ipc:` namespace:
  - camera ring (produced by the Rust webcam-server) → raw MJPEG feed;
  - processed ring (produced by inference-service Stage D) → detection-overlaid
    MJPEG feed.

The ring layouts live in the shared `conecsa_shm` package (in conecsa-os-base:base);
this module only owns the MJPEG fan-out. Each HTTP client gets its own generator
that polls the latest slot lock-free (single-producer / multi-consumer,
latest-wins), so many simultaneous viewers fan out from one capture.
"""
import logging
import time

import cv2
import numpy as np

from conecsa_shm.camera_ring import CameraRingReader
from conecsa_shm.processed_ring import ProcessedFrameReader
from conecsa_shm.stereo import combine_stereo

from .config import settings

logger = logging.getLogger(__name__)


def format_mjpeg_frame(jpg: bytes) -> bytes:
    """Wrap JPEG bytes in a multipart/x-mixed-replace boundary part."""
    return (b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n")


# Module-level readers (the mmaps are shared/lock-free, safe across threads).
# CameraRingReader.get_latest() returns a ready-to-stream JPEG (RAW frames are
# encoded); read-only since the gateway never pushes camera config.
_camera = CameraRingReader(settings.CAMERA_SHM_NAME, writable=False)
_processed = ProcessedFrameReader(settings.PROCESSED_SHM_NAME)

# Idle poll interval — keep CPU usage reasonable under many concurrent clients.
_POLL_S = 0.01


def _generate(reader):
    """Yield an MJPEG multipart stream from a SHM frame *reader* (latest-wins)."""
    last = 0
    idle = 0.0
    while True:
        got = reader.get_latest(last)
        if got is not None:
            jpg, last = got
            idle = 0.0
            yield format_mjpeg_frame(jpg)
        else:
            time.sleep(_POLL_S)
            idle += _POLL_S
            # If the producer is gone for a while, keep the connection alive by
            # re-checking; readers transparently re-open the segment.
            if idle > 5.0:
                idle = 0.0


def generate_raw():
    """MJPEG generator for /api/v1/video_feed (raw camera frames)."""
    return _generate(_camera)


def generate_processed():
    """MJPEG generator for /api/v1/video_feed_processed (detection overlay)."""
    return _generate(_processed)


# Training preview pacing: ~10 fps is plenty for framing captures and bounds
# the gateway-side decode/encode CPU cost (inference is stopped on this page,
# so the processed feed is frozen and unusable here).
_PREVIEW_INTERVAL_S = 0.1
_PREVIEW_WIDTH = 640

# Live stereo-config cache for the preview. The stereo alignment sliders write
# to the inference-service's camera config (ManagementControl.UpdateCamera);
# the preview must read the SAME values or slider changes would be invisible
# here (and captures would not match the aligned view). A short TTL keeps
# slider feedback snappy without a gRPC call per frame.
_STEREO_TTL_S = 1.0
_stereo_cache = {"at": 0.0, "value": None}


def get_live_stereo():
    """Return ``(enabled, alpha, offset, offset_y)`` from the live camera
    config, falling back to the env defaults when the inference-service is
    unreachable."""
    now = time.monotonic()
    if _stereo_cache["value"] is not None and now - _stereo_cache["at"] < _STEREO_TTL_S:
        return _stereo_cache["value"]
    value = (
        settings.STEREO_COMBINE == "blend",
        settings.STEREO_BLEND_ALPHA,
        settings.STEREO_OFFSET,
        settings.STEREO_OFFSET_Y,
    )
    try:
        import json

        from .grpc_clients import clients, inf

        cfg = json.loads(clients.management.GetCamera(inf.Empty(), timeout=2).json)
        value = (
            bool(cfg.get("current_stereo_enabled", value[0])),
            float(cfg.get("current_stereo_blend_alpha", value[1])),
            float(cfg.get("current_stereo_offset", value[2])),
            float(cfg.get("current_stereo_offset_y", value[3])),
        )
    except Exception as exc:  # noqa: BLE001 - preview must keep running
        logger.debug("live stereo config unavailable (%s); using defaults", exc)
    _stereo_cache["at"] = now
    _stereo_cache["value"] = value
    return value


def generate_training_preview():
    """MJPEG generator for /api/v1/training/preview.

    Decodes the raw camera frame, applies the same stereo combine the dataset
    capture (and the live detector) uses, downscales to the labeling width and
    re-encodes. CPU-only — no GPU involvement while the runtime is released.
    """
    last = 0
    while True:
        frame_start = time.monotonic()
        got = _camera.get_latest(last)
        if got is None:
            time.sleep(_POLL_S)
            continue
        jpg, last = got
        frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        enabled, alpha, offset, offset_y = get_live_stereo()
        if enabled:
            frame = combine_stereo(
                frame, alpha=alpha, offset=offset, offset_y=offset_y
            )
        h, w = frame.shape[:2]
        if w > _PREVIEW_WIDTH:
            frame = cv2.resize(
                frame, (_PREVIEW_WIDTH, int(h * _PREVIEW_WIDTH / w)),
                interpolation=cv2.INTER_AREA,
            )
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            yield format_mjpeg_frame(buf.tobytes())
        elapsed = time.monotonic() - frame_start
        if elapsed < _PREVIEW_INTERVAL_S:
            time.sleep(_PREVIEW_INTERVAL_S - elapsed)
