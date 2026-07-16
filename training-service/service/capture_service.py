"""Dataset image capture from the camera SHM ring.

Replicates the live detector's view: the side-by-side stereo frame is blended
into a single half-width image (``conecsa_shm.stereo`` — same math as the
inference-service), then letterboxed to the 640×640 training resolution with
the YOLO gray padding (114). Letterboxing (not stretching) keeps the dataset
geometry identical to what the detector sees at inference time.
"""
import logging
import time
from typing import Optional, Tuple

import cv2
import numpy as np
import requests

from conecsa_shm.camera_ring import CameraRingReader
from conecsa_shm.stereo import combine_stereo

from .config import Config

logger = logging.getLogger(__name__)

_PAD_COLOR = (114, 114, 114)


class CaptureService:
    """Captures the current camera frame from the shared camera SHM ring.

    Applies the same stereo-combine geometry as the inference-service so
    captured dataset images match what the live detector sees.
    """

    def __init__(self, config: Config):
        self._config = config
        self._reader = CameraRingReader(config.SHM_NAME)
        self._last_seq = 0

    def _live_stereo(self) -> Tuple[bool, float, float, float]:
        """Stereo combine parameters from the live camera config.

        The user aligns the stereo blend with the overlay sliders, which write
        to the inference-service's camera config — captures must use those same
        values (not the env defaults) or the dataset wouldn't match the aligned
        view. Falls back to env defaults when the gateway is unreachable.
        Captures are rare, so one HTTP round-trip each is fine.
        """
        enabled = self._config.STEREO_COMBINE == "blend"
        alpha = self._config.STEREO_BLEND_ALPHA
        offset = self._config.STEREO_OFFSET
        offset_y = self._config.STEREO_OFFSET_Y
        try:
            cfg = requests.get(
                f"{self._config.GATEWAY_ADDR}/api/v1/camera/devices", timeout=3
            ).json()
            enabled = bool(cfg.get("current_stereo_enabled", enabled))
            alpha = float(cfg.get("current_stereo_blend_alpha", alpha))
            offset = float(cfg.get("current_stereo_offset", offset))
            offset_y = float(cfg.get("current_stereo_offset_y", offset_y))
        except Exception as exc:  # noqa: BLE001 - capture must keep working
            logger.warning("live stereo config unavailable (%s); using defaults", exc)
        return enabled, alpha, offset, offset_y

    def grab_combined(self) -> Optional[np.ndarray]:
        """Return the latest camera frame, stereo-combined, BGR."""
        # Re-read up to ~1s: right after start the ring may not have a frame
        # newer than what we last consumed.
        deadline = time.monotonic() + 1.0
        got = None
        while got is None and time.monotonic() < deadline:
            got = self._reader.get_latest_frame(self._last_seq)
            if got is None:
                time.sleep(0.02)
        if got is None:
            return None
        frame, seq = got
        self._last_seq = seq
        if isinstance(frame, (bytes, bytearray)):
            frame = cv2.imdecode(np.frombuffer(frame, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        enabled, alpha, offset, offset_y = self._live_stereo()
        if enabled:
            frame = combine_stereo(frame, alpha=alpha, offset=offset, offset_y=offset_y)
        return frame

    def capture_letterboxed(self) -> Optional[bytes]:
        """Capture one frame as a 640×640 letterboxed JPEG (dataset format)."""
        frame = self.grab_combined()
        if frame is None:
            logger.warning("Capture failed: no camera frame available")
            return None
        boxed = letterbox_square(frame, self._config.IMG_SIZE)
        ok, buf = cv2.imencode(".jpg", boxed, [cv2.IMWRITE_JPEG_QUALITY, 90])
        return buf.tobytes() if ok else None


def letterbox_square(frame: np.ndarray, size: int) -> np.ndarray:
    """Scale to fit a size×size square and pad the rest with YOLO gray."""
    h, w = frame.shape[:2]
    scale = min(size / w, size / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
    top = (size - nh) // 2
    left = (size - nw) // 2
    return cv2.copyMakeBorder(
        resized, top, size - nh - top, left, size - nw - left,
        cv2.BORDER_CONSTANT, value=_PAD_COLOR,
    )


def corners_to_letterbox(
    x1: float, y1: float, x2: float, y2: float,
    src_w: int, src_h: int, size: int,
) -> Tuple[float, float, float, float]:
    """Map normalized corners on a src_w×src_h frame to normalized YOLO
    (cx, cy, w, h) on the size×size letterboxed image.

    Mirrors ``letterbox_square``'s exact rounding so labels land where the
    pixels do.
    """
    scale = min(size / src_w, size / src_h)
    nw, nh = max(1, int(round(src_w * scale))), max(1, int(round(src_h * scale)))
    top = (size - nh) // 2
    left = (size - nw) // 2
    lx1, lx2 = (x1 * nw + left) / size, (x2 * nw + left) / size
    ly1, ly2 = (y1 * nh + top) / size, (y2 * nh + top) / size

    def _clamp(v: float) -> float:
        return min(1.0, max(0.0, v))

    cx, cy = _clamp((lx1 + lx2) / 2.0), _clamp((ly1 + ly2) / 2.0)
    w, h = _clamp(lx2 - lx1), _clamp(ly2 - ly1)
    return cx, cy, w, h
