"""Unit tests for ModelSettingsService (per-model settings JSON sidecar)."""
import json
from types import SimpleNamespace

import pytest

from api.services.model_settings_service import ModelSettingsService


class FakeVideo:
    def __init__(self, camera=None, stereo=None):
        self._camera = camera or {"framerate": 30}
        self._stereo = stereo or {"enabled": False, "alpha": 0.5}
        self.applied_camera = []
        self.applied_stereo = []

    def get_current_camera_config(self):
        return self._camera

    def get_stereo_config(self):
        return self._stereo

    def apply_webcam_server_config(self, camera):
        self.applied_camera.append(camera)

    def set_stereo_config(self, enabled, alpha, offset, offset_y):
        self.applied_stereo.append((enabled, alpha, offset, offset_y))


@pytest.fixture
def config():
    return SimpleNamespace(CONFIDENCE_THRESHOLD=0.5, OVERLAY_THRESHOLD=0.5)


class TestSave:
    def test_no_path_is_a_noop(self, config, tmp_path):
        svc = ModelSettingsService(config)
        svc.save()
        assert list(tmp_path.iterdir()) == []

    def test_snapshot_includes_thresholds_camera_and_stereo(self, config, tmp_path):
        video = FakeVideo(camera={"gain": 10}, stereo={"enabled": True})
        svc = ModelSettingsService(config, video_service=video)
        path = tmp_path / "weights.settings.json"
        svc.switch_model(str(path))

        data = json.loads(path.read_text())
        assert data["thresholds"] == {"confidence": 0.5, "overlay": 0.5}
        assert data["camera"] == {"gain": 10}
        assert data["stereo"] == {"enabled": True}

    def test_snapshot_without_video_service_has_thresholds_only(self, config, tmp_path):
        svc = ModelSettingsService(config)
        path = tmp_path / "weights.settings.json"
        svc.switch_model(str(path))

        data = json.loads(path.read_text())
        assert set(data) == {"thresholds"}


class TestSwitchModel:
    def test_missing_file_is_seeded_from_live_state(self, config, tmp_path):
        config.CONFIDENCE_THRESHOLD = 0.7
        svc = ModelSettingsService(config)
        path = tmp_path / "new.settings.json"
        svc.switch_model(str(path))

        assert json.loads(path.read_text())["thresholds"]["confidence"] == 0.7

    def test_existing_file_is_loaded_and_applied(self, config, tmp_path):
        path = tmp_path / "weights.settings.json"
        path.write_text(json.dumps({"thresholds": {"confidence": 0.9, "overlay": 0.2}}))

        ModelSettingsService(config).switch_model(str(path))
        assert config.CONFIDENCE_THRESHOLD == 0.9
        assert config.OVERLAY_THRESHOLD == 0.2


class TestLoadAndApply:
    def _load(self, config, tmp_path, payload, video=None):
        path = tmp_path / "weights.settings.json"
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        svc = ModelSettingsService(config, video_service=video)
        svc.switch_model(str(path))
        return svc

    def test_out_of_range_thresholds_are_ignored(self, config, tmp_path):
        self._load(config, tmp_path, {"thresholds": {"confidence": 1.5, "overlay": -0.1}})
        assert config.CONFIDENCE_THRESHOLD == 0.5
        assert config.OVERLAY_THRESHOLD == 0.5

    def test_non_numeric_thresholds_are_ignored(self, config, tmp_path):
        self._load(config, tmp_path, {"thresholds": {"confidence": "high", "overlay": None}})
        assert config.CONFIDENCE_THRESHOLD == 0.5
        assert config.OVERLAY_THRESHOLD == 0.5

    def test_corrupt_file_leaves_state_untouched(self, config, tmp_path):
        self._load(config, tmp_path, "{not json")
        assert config.CONFIDENCE_THRESHOLD == 0.5

    def test_camera_config_is_forwarded_to_video_service(self, config, tmp_path):
        video = FakeVideo()
        self._load(config, tmp_path, {"camera": {"framerate": 15}}, video=video)
        assert video.applied_camera == [{"framerate": 15}]

    def test_stereo_config_is_forwarded_field_by_field(self, config, tmp_path):
        video = FakeVideo()
        self._load(
            config,
            tmp_path,
            {"stereo": {"enabled": True, "alpha": 0.3, "offset": 0.1, "offset_y": -0.2}},
            video=video,
        )
        assert video.applied_stereo == [(True, 0.3, 0.1, -0.2)]
