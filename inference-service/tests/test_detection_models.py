"""Unit tests for the detection dataclasses."""
import numpy as np

from api.models.detection_models import (
    Detection,
    DetectionResult,
    ModelInfo,
    SystemStats,
)


class TestDetection:
    def test_fields_and_default_area(self):
        det = Detection(
            class_id=2,
            class_name="cat",
            confidence=0.8,
            bbox=(1, 2, 3, 4),
            center=(2, 3),
        )
        assert det.class_id == 2
        assert det.class_name == "cat"
        assert det.bbox == (1, 2, 3, 4)
        assert det.center == (2, 3)
        assert det.area is None

    def test_area_can_be_set(self):
        area = {"id": "a1", "label": "zone", "shape": {}}
        det = Detection(0, "x", 0.5, (0, 0, 1, 1), (0, 0), area=area)
        assert det.area == area


class TestSystemStats:
    def test_defaults_are_zero(self):
        stats = SystemStats()
        assert stats.fps == 0.0
        assert stats.inference_time == 0.0
        assert stats.detections == 0
        assert stats.frames_with_detections == 0

    def test_custom_values(self):
        stats = SystemStats(fps=30.0, inference_time=0.02, detections=5)
        assert stats.fps == 30.0
        assert stats.detections == 5


class TestModelInfo:
    def test_defaults_is_active_false(self):
        info = ModelInfo(name="m", path="/p", size=10, modified=1.0)
        assert info.is_active is False

    def test_explicit_active(self):
        info = ModelInfo("m", "/p", 10, 1.0, is_active=True)
        assert info.is_active is True


class TestDetectionResult:
    def test_holds_image_and_metadata(self):
        img = np.zeros((2, 2, 3), dtype=np.uint8)
        result = DetectionResult(
            detections=[], processed_image=img, inference_time=0.01, num_detections=0
        )
        assert result.num_detections == 0
        assert result.processed_image.shape == (2, 2, 3)
        assert result.detections == []
        assert result.raw_image is None

    def test_raw_image_can_be_set(self):
        img = np.zeros((2, 2, 3), dtype=np.uint8)
        raw = np.ones((2, 2, 3), dtype=np.uint8)
        result = DetectionResult(
            detections=[], processed_image=img, inference_time=0.01,
            num_detections=0, raw_image=raw,
        )
        assert result.raw_image is raw
