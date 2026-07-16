"""Unit tests for the frame codec service (pure image ops)."""
import cv2
import numpy as np
import pytest

from api.services.frame_codec import (
    FrameCodecService,
    decode_frame_scaled,
    encode_frame,
)


def _jpeg_bytes(h=64, w=64):
    frame = np.full((h, w, 3), 120, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes(), frame


class TestEncodeDecode:
    def test_encode_returns_jpeg_magic(self):
        frame = np.zeros((16, 16, 3), dtype=np.uint8)
        data = encode_frame(frame)
        assert data is not None
        assert data[:2] == b"\xff\xd8"  # JPEG SOI marker

    def test_decode_scaled_full_res(self):
        jpg, frame = _jpeg_bytes(64, 64)
        decoded = decode_frame_scaled(jpg, scale=1)
        assert decoded is not None
        assert decoded.shape == frame.shape

    def test_decode_scaled_half_res(self):
        jpg, _ = _jpeg_bytes(64, 64)
        decoded = decode_frame_scaled(jpg, scale=2)
        assert decoded is not None
        assert decoded.shape[0] == 32 and decoded.shape[1] == 32

    def test_decode_unknown_scale_falls_back_to_half(self):
        jpg, _ = _jpeg_bytes(64, 64)
        decoded = decode_frame_scaled(jpg, scale=3)
        assert decoded is not None
        assert decoded.shape[0] == 32

    def test_decode_garbage_returns_none(self):
        assert decode_frame_scaled(b"not a jpeg", scale=1) is None


class TestApplyRgbLevels:
    def test_neutral_is_noop_identity(self):
        frame = np.full((4, 4, 3), 100, dtype=np.uint8)
        out = FrameCodecService.apply_rgb_levels(frame, 128, 128, 128)
        # Returns the same array unchanged.
        assert out is frame

    def test_none_frame_passthrough(self):
        assert FrameCodecService.apply_rgb_levels(None, 200, 128, 128) is None

    def test_doubling_red_channel(self):
        frame = np.full((2, 2, 3), 100, dtype=np.uint8)  # BGR all 100
        out = FrameCodecService.apply_rgb_levels(frame, 256, 128, 128)
        assert out is not None
        # R channel (index 2) scaled by 256/128 = 2 -> 200; others unchanged.
        assert np.all(out[:, :, 2] == 200)
        assert np.all(out[:, :, 1] == 100)
        assert np.all(out[:, :, 0] == 100)

    def test_clamps_to_255(self):
        frame = np.full((2, 2, 3), 200, dtype=np.uint8)
        out = FrameCodecService.apply_rgb_levels(frame, 255, 128, 128)
        assert out is not None
        assert out[:, :, 2].max() <= 255
        assert np.all(out[:, :, 2] == 255)


class TestCombineStereo:
    def test_disabled_returns_frame_unchanged(self, monkeypatch):
        monkeypatch.delenv("STEREO_COMBINE", raising=False)
        svc = FrameCodecService()
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        assert svc.combine_stereo(frame) is frame

    def test_none_frame(self, monkeypatch):
        monkeypatch.setenv("STEREO_COMBINE", "blend")
        svc = FrameCodecService()
        assert svc.combine_stereo(None) is None

    def test_enabled_halves_width(self, monkeypatch):
        monkeypatch.setenv("STEREO_COMBINE", "blend")
        svc = FrameCodecService()
        frame = np.zeros((10, 20, 3), dtype=np.uint8)
        out = svc.combine_stereo(frame)
        assert out is not None
        assert out.shape == (10, 10, 3)


class TestStereoConfig:
    def test_set_and_get_roundtrip(self, monkeypatch):
        monkeypatch.delenv("STEREO_COMBINE", raising=False)
        svc = FrameCodecService()
        svc.set_stereo_config(enabled=True, alpha=0.7, offset=0.2, offset_y=-0.1)
        cfg = svc.get_stereo_config()
        assert cfg["enabled"] is True
        assert cfg["alpha"] == pytest.approx(0.7)
        assert cfg["offset"] == pytest.approx(0.2)
        assert cfg["offset_y"] == pytest.approx(-0.1)

    def test_values_are_clamped(self):
        svc = FrameCodecService()
        svc.set_stereo_config(alpha=5.0, offset=9.0, offset_y=-9.0)
        cfg = svc.get_stereo_config()
        assert cfg["alpha"] == 1.0
        assert cfg["offset"] == 0.5
        assert cfg["offset_y"] == -0.5

    def test_partial_update_keeps_others(self):
        svc = FrameCodecService()
        svc.set_stereo_config(alpha=0.3)
        before = svc.get_stereo_config()["offset"]
        svc.set_stereo_config(offset=0.25)
        assert svc.get_stereo_config()["alpha"] == pytest.approx(0.3)
        assert svc.get_stereo_config()["offset"] == pytest.approx(0.25)
        assert before == 0.0
