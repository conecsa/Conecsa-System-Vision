"""Unit tests for ConfigService (get/update of the capture + inference config)."""
from types import SimpleNamespace

import pytest

from api.services.config_service import ConfigService


class FakeVideo:
    def __init__(self):
        self.patches = []

    def apply_webcam_server_config(self, patch):
        self.patches.append(patch)


class FakeSettings:
    def __init__(self):
        self.saved = 0

    def save(self):
        self.saved += 1


@pytest.fixture
def config():
    return SimpleNamespace(
        CAPTURE_DEVICE="/dev/video0",
        CAPTURE_RESOLUTION_X=640,
        CAPTURE_RESOLUTION_Y=480,
        CAPTURE_FRAMERATE=30,
        MODEL_PATH="/models/best.engine",
        CONFIDENCE_THRESHOLD=0.5,
    )


class TestGetConfig:
    def test_maps_config_fields(self, config):
        svc = ConfigService(config)
        assert svc.get_config() == {
            "capture_device": "/dev/video0",
            "capture_resolution": [640, 480],
            "capture_framerate": 30,
            "model_path": "/models/best.engine",
            "confidence_threshold": 0.5,
        }


class TestUpdateConfig:
    def test_empty_data_is_rejected(self, config):
        ok, msg = ConfigService(config).update_config({})
        assert ok is False
        assert msg == "No data provided"

    def test_device_path_is_stripped_to_camera_index(self, config):
        video = FakeVideo()
        ok, _ = ConfigService(config, video_service=video).update_config(
            {"capture_device": "/dev/video2"}
        )
        assert ok is True
        assert config.CAPTURE_DEVICE == "/dev/video2"
        assert video.patches == [{"camera_index": 2}]

    def test_bare_numeric_device_is_accepted(self, config):
        video = FakeVideo()
        ConfigService(config, video_service=video).update_config({"capture_device": "1"})
        assert video.patches == [{"camera_index": 1}]

    def test_non_numeric_device_skips_the_webcam_push(self, config):
        video = FakeVideo()
        ok, _ = ConfigService(config, video_service=video).update_config(
            {"capture_device": "usb-cam"}
        )
        # Config is still updated; only the camera-index push is skipped.
        assert ok is True
        assert config.CAPTURE_DEVICE == "usb-cam"
        assert video.patches == []

    def test_framerate_is_coerced_and_pushed(self, config):
        video = FakeVideo()
        ok, _ = ConfigService(config, video_service=video).update_config(
            {"capture_framerate": "60"}
        )
        assert ok is True
        assert config.CAPTURE_FRAMERATE == 60
        assert video.patches == [{"framerate": 60}]

    def test_invalid_framerate_reports_the_error(self, config):
        ok, msg = ConfigService(config).update_config({"capture_framerate": "fast"})
        assert ok is False
        assert msg  # the ValueError text is surfaced

    def test_confidence_threshold_is_coerced_to_float(self, config):
        ok, _ = ConfigService(config).update_config({"confidence_threshold": "0.7"})
        assert ok is True
        assert config.CONFIDENCE_THRESHOLD == 0.7

    def test_settings_are_persisted_after_update(self, config):
        settings = FakeSettings()
        ConfigService(config, settings_service=settings).update_config(
            {"confidence_threshold": 0.3}
        )
        assert settings.saved == 1

    def test_works_without_optional_collaborators(self, config):
        ok, msg = ConfigService(config).update_config({"capture_device": "/dev/video1"})
        assert ok is True
        assert msg == "Configuration updated"
