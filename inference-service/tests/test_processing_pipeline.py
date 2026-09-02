"""Unit tests for the pure helpers of the processing pipeline (no threads)."""
import numpy as np
import pytest
from api.services.processing_pipeline import downscale_for_publish, output_scale_from_env


class TestOutputScaleFromEnv:
    def test_default_is_one(self, monkeypatch):
        monkeypatch.delenv("PROCESSED_OUTPUT_SCALE", raising=False)
        assert output_scale_from_env() == 1

    @pytest.mark.parametrize("raw,expected", [("1", 1), ("2", 2), ("4", 4), (" 2 ", 2)])
    def test_accepted_factors(self, monkeypatch, raw, expected):
        monkeypatch.setenv("PROCESSED_OUTPUT_SCALE", raw)
        assert output_scale_from_env() == expected

    @pytest.mark.parametrize("raw", ["0", "3", "8", "-2", "two", ""])
    def test_invalid_values_fall_back_to_one(self, monkeypatch, raw):
        monkeypatch.setenv("PROCESSED_OUTPUT_SCALE", raw)
        assert output_scale_from_env() == 1


class TestDownscaleForPublish:
    def test_factor_one_returns_same_object(self):
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        assert downscale_for_publish(frame, 1) is frame

    @pytest.mark.parametrize("factor", [2, 4])
    def test_factor_shrinks_both_axes(self, factor):
        frame = np.full((720, 1280, 3), 90, dtype=np.uint8)
        out = downscale_for_publish(frame, factor)
        assert out.shape == (720 // factor, 1280 // factor, 3)
        assert out.dtype == np.uint8
        assert np.all(out == 90)

    def test_too_small_frame_is_left_alone(self):
        frame = np.zeros((1, 3, 3), dtype=np.uint8)
        assert downscale_for_publish(frame, 2) is frame
