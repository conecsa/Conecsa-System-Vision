"""Side-by-side stereo combine, shared by training-service and api-gateway.

The USB stereo camera packs the two eyes left|right in one frame. The
inference-service splits it in half and blends the eyes before detection
(`FrameCodecService.combine_stereo`); this is a pure-function copy of that
logic so dataset capture and the training preview see the exact same geometry
the live detector does. The inference hot path keeps its own copy on purpose —
this module must stay dependency-free (numpy/cv2 only) and changing it must
never risk the detection pipeline.
"""
from typing import Optional, overload

import cv2
import numpy as np


# None passes through unchanged, so a non-None frame always yields a frame —
# the overloads let callers that already hold a frame keep its narrowed type.
@overload
def combine_stereo(
    frame: np.ndarray,
    alpha: float = ...,
    offset: float = ...,
    offset_y: float = ...,
) -> np.ndarray: ...


@overload
def combine_stereo(
    frame: None,
    alpha: float = ...,
    offset: float = ...,
    offset_y: float = ...,
) -> None: ...


def combine_stereo(
    frame: Optional[np.ndarray],
    alpha: float = 0.5,
    offset: float = 0.0,
    offset_y: float = 0.0,
) -> Optional[np.ndarray]:
    """Blend a side-by-side stereo frame into a single half-width image.

    ``alpha`` weighs the left eye (0..1); ``offset``/``offset_y`` shift the
    right eye by a fraction of the half-width/height (-0.5..0.5) to control
    overlap alignment. Returns the frame unchanged when it is ``None`` or too
    narrow to split.
    """
    if frame is None:
        return frame
    h, w = frame.shape[:2]
    if w < 2:
        return frame
    alpha = min(max(float(alpha), 0.0), 1.0)
    offset = min(max(float(offset), -0.5), 0.5)
    offset_y = min(max(float(offset_y), -0.5), 0.5)
    half = w // 2
    left = frame[:, :half]
    right = frame[:, w - half:]
    sx = int(round(offset * half))
    sy = int(round(offset_y * h))
    if sx != 0 or sy != 0:
        m = np.array([[1, 0, sx], [0, 1, sy]], dtype=np.float32)
        right = cv2.warpAffine(right, m, (half, h))
    return cv2.addWeighted(left, alpha, right, 1.0 - alpha, 0.0)
