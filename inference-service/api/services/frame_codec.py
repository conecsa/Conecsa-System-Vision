"""
Frame codec service - pure image operations for the video pipeline.

Groups the JPEG decode/encode, reduced-scale decode, stereo combine and
software RGB level correction that used to live on ``VideoService``. These are
the CPU stages of the processing pipeline; they all release the GIL inside
OpenCV, so they parallelise across cores when run on the pipeline's worker
threads.

(The name avoids ``ConversionService``, which already exists for *model*
conversion pt→onnx→engine.)
"""
import logging
import os
from typing import Dict, Optional

# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

# noinspection PyPackageRequirements
import cv2  # Package is included on os build.

logger = logging.getLogger(__name__)


# Map PROCESSING_DECODE_SCALE -> OpenCV reduced-decode flag. Decoding the JPEG
# at a reduced scale (scaled IDCT inside libjpeg-turbo) is several times cheaper
# than a full-resolution decode. The detector resizes to ~640 internally, so
# there is no accuracy cost, and it decouples inference/overlay cost from the
# user-selected capture resolution.
_REDUCED_DECODE_FLAGS = {
    1: cv2.IMREAD_COLOR,
    2: cv2.IMREAD_REDUCED_COLOR_2,
    4: cv2.IMREAD_REDUCED_COLOR_4,
    8: cv2.IMREAD_REDUCED_COLOR_8,
}


def decode_frame_scaled(jpg_bytes: bytes, scale: int = 2) -> Optional[np.ndarray]:
    """Decode JPEG bytes to a BGR ndarray at 1/``scale`` resolution.

    Falls back to half-resolution for unrecognised scale values.
    """
    try:
        flag = _REDUCED_DECODE_FLAGS.get(scale, cv2.IMREAD_REDUCED_COLOR_2)
        return cv2.imdecode(np.frombuffer(jpg_bytes, dtype=np.uint8), flag)
    except Exception as ex:
        logger.error(f"Failed to decode frame (scaled x1/{scale}): {ex}")
        return None


def encode_frame(frame: np.ndarray, quality: int = 85) -> Optional[bytes]:
    """Encode a numpy array to JPEG bytes."""
    try:
        ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if ret:
            return buffer.tobytes()
        return None
    except Exception as ex:
        logger.error(f"Failed to encode frame: {ex}")
        return None


class FrameCodecService:
    """Stateful image codec: decode scale + stereo-combine configuration.

    RGB level correction is intentionally stateless (values are passed in) — the
    levels are part of the camera configuration owned by ``VideoService``.
    """

    def __init__(self):
        # Reduced-scale decode factor for the processed stream / inference path.
        # 1 = full res, 2 = half, 4 = quarter, 8 = eighth.
        self._decode_scale = int(os.environ.get("PROCESSING_DECODE_SCALE", 2))

        # Stereo combine: a side-by-side (left|right) frame is split in half and
        # the two eyes are alpha-blended into a single image, used for both the
        # displayed stream and YOLO inference. Runtime-toggleable from the UI;
        # env vars only seed the defaults.
        self._stereo_enabled = os.environ.get("STEREO_COMBINE", "none").strip().lower() == "blend"
        try:
            self._stereo_alpha = float(os.environ.get("STEREO_BLEND_ALPHA", 0.5))
        except ValueError:
            self._stereo_alpha = 0.5
        self._stereo_alpha = min(max(self._stereo_alpha, 0.0), 1.0)
        # Overlap: fraction of eye-width / -height to shift the right eye over
        # the left before blending (-0.5..0.5 each axis). Lets the user align
        # the two views (horizontally and vertically) to reduce ghosting.
        try:
            self._stereo_offset = float(os.environ.get("STEREO_OFFSET", 0.0))
        except ValueError:
            self._stereo_offset = 0.0
        self._stereo_offset = min(max(self._stereo_offset, -0.5), 0.5)
        try:
            self._stereo_offset_y = float(os.environ.get("STEREO_OFFSET_Y", 0.0))
        except ValueError:
            self._stereo_offset_y = 0.0
        self._stereo_offset_y = min(max(self._stereo_offset_y, -0.5), 0.5)

    # ------------------------------------------------------------------
    # Codec helpers
    # ------------------------------------------------------------------

    def decode_frame_scaled(self, jpg_bytes: bytes) -> Optional[np.ndarray]:
        """Decode JPEG bytes to BGR at the configured processing scale."""
        return decode_frame_scaled(jpg_bytes, self._decode_scale)

    @staticmethod
    def encode_frame(frame: np.ndarray, quality: int = 85) -> Optional[bytes]:
        """JPEG-encode a frame at the given quality (``None`` on failure)."""
        return encode_frame(frame, quality)

    def combine_stereo(self, frame: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """Combine a side-by-side stereo frame into a single image.

        The camera packs the two eyes left|right in one frame, so we split it in
        half and blend the eyes. The result (half width, full height) feeds both
        the displayed stream and YOLO inference. Returns the frame unchanged when
        stereo combine is disabled or the frame is too narrow to split.
        """
        if not self._stereo_enabled or frame is None:
            return frame
        h, w = frame.shape[:2]
        if w < 2:
            return frame
        half = w // 2
        left = frame[:, :half]
        right = frame[:, w - half:]
        # Shift the right eye (X and Y) to control overlap/alignment.
        sx = int(round(self._stereo_offset * half))
        sy = int(round(self._stereo_offset_y * h))
        if sx != 0 or sy != 0:
            m = np.array([[1, 0, sx], [0, 1, sy]], dtype=np.float32)
            right = cv2.warpAffine(right, m, (half, h))
        return cv2.addWeighted(left, self._stereo_alpha, right, 1.0 - self._stereo_alpha, 0.0)

    @staticmethod
    def apply_rgb_levels(frame: Optional[np.ndarray], r: int, g: int, b: int) -> Optional[np.ndarray]:
        """Apply software RGB level gains to a BGR frame (128 = neutral).

        Used for JPEG/passthrough cameras whose driver lacks red/blue balance
        controls (e.g. the USB stereo camera). No-op when all three channels are
        neutral. (Raw-RGB producers already had RGB applied in the webcam-server,
        so this is only called on the JPEG-decode path.)
        """
        if frame is None:
            return frame
        if r == 128 and g == 128 and b == 128:
            return frame
        out = frame.astype(np.float32)
        out[:, :, 0] *= b / 128.0  # B
        out[:, :, 1] *= g / 128.0  # G
        out[:, :, 2] *= r / 128.0  # R
        np.clip(out, 0, 255, out=out)
        return out.astype(np.uint8)

    # ------------------------------------------------------------------
    # Stereo configuration (delegated to from VideoService)
    # ------------------------------------------------------------------

    def get_stereo_config(self) -> Dict:
        """Return the current stereo combine settings."""
        return {
            "enabled": self._stereo_enabled,
            "alpha": self._stereo_alpha,
            "offset": self._stereo_offset,
            "offset_y": self._stereo_offset_y,
        }

    def set_stereo_config(
        self,
        enabled: Optional[bool] = None,
        alpha: Optional[float] = None,
        offset: Optional[float] = None,
        offset_y: Optional[float] = None,
    ) -> None:
        """Update stereo combine settings (partial; unset fields are kept)."""
        if enabled is not None:
            self._stereo_enabled = bool(enabled)
        if alpha is not None:
            self._stereo_alpha = min(max(float(alpha), 0.0), 1.0)
        if offset is not None:
            self._stereo_offset = min(max(float(offset), -0.5), 0.5)
        if offset_y is not None:
            self._stereo_offset_y = min(max(float(offset_y), -0.5), 0.5)
