"""
Data models for object detection system.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

# noinspection PyPackageRequirements
import numpy as np # Installed on os build.


@dataclass
class Detection:
    """Represents a single object detection."""
    class_id: int
    class_name: str
    confidence: float
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2)
    center: Tuple[int, int]  # (center_x, center_y)
    # Box color as "#rrggbb", resolved from the class entry's "name #hex"
    # suffix or, absent one, from the generated palette. Travels with the
    # detection so client-side overlays match the burned-in one.
    color: Optional[str] = None
    # Saved detection area whose shape contains this detection's center, as
    # {"id", "label", "shape"}; None when no saved area contains it. Assigned
    # in YOLODetector._filter_detections_by_areas. A center may fall inside
    # several overlapping areas — the first match (by area order) wins.
    area: Optional[dict] = None


@dataclass
class DetectionResult:
    """Result of a detection operation."""
    detections: List[Detection]
    processed_image: np.ndarray
    inference_time: float
    num_detections: int
    # Pristine frame (no overlay), held by reference — safe because every
    # pipeline frame is a freshly allocated buffer and the detector draws on a
    # copy. Must become a copy if the pipeline ever reuses frame buffers.
    raw_image: Optional[np.ndarray] = None


@dataclass
class SystemStats:
    """System performance statistics."""
    fps: float = 0.0
    inference_time: float = 0.0
    detections: int = 0
    frames_with_detections: int = 0


@dataclass
class ModelInfo:
    """Information about a model file."""
    name: str
    path: str
    size: int
    modified: float
    is_active: bool = False

