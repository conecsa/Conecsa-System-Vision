"""Unit tests for the pure snapshot helpers of the detection service."""
import pytest

from api.services.detection_service import normalized_bbox


class TestNormalizedBbox:
    def test_maps_pixel_corners_to_unit_range(self):
        assert normalized_bbox((160, 90, 320, 180), 640, 360) == [
            0.25, 0.25, 0.5, 0.5,
        ]

    def test_full_frame_box(self):
        assert normalized_bbox((0, 0, 640, 360), 640, 360) == [0.0, 0.0, 1.0, 1.0]

    def test_clamps_out_of_frame_corners(self):
        # NMS/decoding can produce corners slightly outside the frame.
        assert normalized_bbox((-10, -5, 700, 400), 640, 360) == [
            0.0, 0.0, 1.0, 1.0,
        ]

    def test_rounds_to_four_decimals(self):
        out = normalized_bbox((1, 1, 2, 2), 3, 3)
        assert out == [
            pytest.approx(0.3333), pytest.approx(0.3333),
            pytest.approx(0.6667), pytest.approx(0.6667),
        ]
        assert all(v == round(v, 4) for v in out)
