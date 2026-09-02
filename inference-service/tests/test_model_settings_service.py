"""Unit tests for ModelSettingsService (per-model settings JSON sidecar)."""
import json
from types import SimpleNamespace

import pytest
from api.services.model_settings_service import (
    ModelSettingsService,
    geometry_mismatch,
    parse_train_geometry,
)


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


class TestImgsz:
    def test_record_creates_a_file_with_only_imgsz(self, tmp_path):
        path = tmp_path / "weights.settings.json"
        ModelSettingsService.record_imgsz(str(path), 1280)
        assert json.loads(path.read_text()) == {"imgsz": 1280}

    def test_record_merges_into_an_existing_file(self, tmp_path):
        path = tmp_path / "weights.settings.json"
        path.write_text(json.dumps({"thresholds": {"confidence": 0.9, "overlay": 0.2}}))
        ModelSettingsService.record_imgsz(str(path), 640)
        data = json.loads(path.read_text())
        assert data["imgsz"] == 640
        assert data["thresholds"] == {"confidence": 0.9, "overlay": 0.2}

    def test_first_activation_completes_a_conversion_seeded_file(self, config, tmp_path):
        path = tmp_path / "weights.settings.json"
        ModelSettingsService.record_imgsz(str(path), 1280)
        config.CONFIDENCE_THRESHOLD = 0.7

        ModelSettingsService(config).switch_model(str(path))

        data = json.loads(path.read_text())
        assert data["imgsz"] == 1280
        assert data["thresholds"]["confidence"] == 0.7

    def test_save_carries_imgsz_over(self, config, tmp_path):
        path = tmp_path / "weights.settings.json"
        path.write_text(json.dumps({"imgsz": 1280, "thresholds": {"confidence": 0.5, "overlay": 0.5}}))
        svc = ModelSettingsService(config)
        svc.switch_model(str(path))
        config.CONFIDENCE_THRESHOLD = 0.3
        svc.save()
        data = json.loads(path.read_text())
        assert data["imgsz"] == 1280
        assert data["thresholds"]["confidence"] == 0.3

    def test_files_without_imgsz_load_unchanged(self, config, tmp_path):
        path = tmp_path / "weights.settings.json"
        original = {"thresholds": {"confidence": 0.9, "overlay": 0.2}}
        path.write_text(json.dumps(original))
        ModelSettingsService(config).switch_model(str(path))
        assert json.loads(path.read_text()) == original
        assert config.CONFIDENCE_THRESHOLD == 0.9

    def test_imgsz_is_informational_only(self, config, tmp_path):
        path = tmp_path / "weights.settings.json"
        path.write_text(json.dumps({"imgsz": "1280x", "thresholds": {"confidence": 0.5,
                                                                      "overlay": 0.5}}))
        svc = ModelSettingsService(config)
        svc.switch_model(str(path))
        svc.save()
        # A malformed value is dropped rather than propagated.
        assert "imgsz" not in json.loads(path.read_text())


class TestTrainingGeometry:
    def test_record_training_writes_imgsz_and_geometry(self, tmp_path):
        path = tmp_path / "weights.settings.json"
        ModelSettingsService.record_training(str(path), 640, "tiles:auto")
        assert json.loads(path.read_text()) == {"imgsz": 640,
                                                "training": {"geometry": "tiles:auto"}}
        assert ModelSettingsService.training_geometry(str(path)) == "tiles:auto"

    def test_unknown_or_malformed_geometry_is_not_recorded(self, tmp_path):
        path = tmp_path / "weights.settings.json"
        ModelSettingsService.record_training(str(path), 640, None)
        assert json.loads(path.read_text()) == {"imgsz": 640}
        ModelSettingsService.record_training(str(path), 640, "tiles:big")
        assert "training" not in json.loads(path.read_text())
        assert ModelSettingsService.training_geometry(str(path)) is None
        assert ModelSettingsService.training_geometry(str(tmp_path / "absent.json")) is None

    def test_save_carries_the_geometry_over(self, config, tmp_path):
        path = tmp_path / "weights.settings.json"
        ModelSettingsService.record_training(str(path), 640, "frames")
        svc = ModelSettingsService(config)
        svc.switch_model(str(path))  # completes the seeded file
        config.CONFIDENCE_THRESHOLD = 0.3
        svc.save()
        data = json.loads(path.read_text())
        assert data["training"] == {"geometry": "frames"}
        assert data["imgsz"] == 640 and data["thresholds"]["confidence"] == 0.3

    @pytest.mark.parametrize("raw,expected", [
        ("frames", "frames"), ("tiles:auto", "tiles:auto"), (" Tiles:720 ", "tiles:720"),
        ("tiles:0", None), ("tiles:", None), ("grid", None), (720, None), (None, None),
    ])
    def test_parse(self, raw, expected):
        assert parse_train_geometry(raw) == expected


class TestGeometryMismatch:
    def test_matching_pairs_are_silent(self):
        assert geometry_mismatch("frames", "off", None) is None
        assert geometry_mismatch("tiles:auto", "grid", None) is None
        assert geometry_mismatch("tiles:720", "grid", 720) is None
        assert geometry_mismatch(None, "grid", None) is None  # unknown: never warned about

    def test_frame_model_under_grid(self):
        assert "TILING_MODE=off" in (geometry_mismatch("frames", "grid", None) or "")

    def test_tile_model_with_tiling_off(self):
        assert "TILING_MODE=grid" in (geometry_mismatch("tiles:auto", "off", None) or "")

    def test_tile_side_disagreement(self):
        assert "TILING_TILE=auto" in (geometry_mismatch("tiles:720", "grid", None) or "")
        assert "TILING_TILE=640" in (geometry_mismatch("tiles:auto", "grid", 640) or "")

    def test_switch_model_logs_the_mismatch(self, config, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("TILING_MODE", raising=False)  # grid by default
        monkeypatch.delenv("TILING_TILE", raising=False)
        path = tmp_path / "frames.settings.json"
        ModelSettingsService.record_training(str(path), 640, "frames")
        with caplog.at_level("WARNING"):
            ModelSettingsService(config).switch_model(str(path))
        assert any("frames.settings.json" in r.message and "TILING_MODE=off" in r.message
                   for r in caplog.records)

    def test_switch_model_is_quiet_when_paired(self, config, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("TILING_MODE", raising=False)
        monkeypatch.delenv("TILING_TILE", raising=False)
        path = tmp_path / "tiles.settings.json"
        ModelSettingsService.record_training(str(path), 640, "tiles:auto")
        with caplog.at_level("WARNING"):
            ModelSettingsService(config).switch_model(str(path))
        assert not [r for r in caplog.records if r.levelname == "WARNING"]
