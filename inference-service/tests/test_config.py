"""Unit tests for the env-driven inference Config."""
import os

from api.config import Config


class TestConfigDefaults:
    def test_defaults(self, monkeypatch):
        for var in (
            "CONFIDENCE_THRESHOLD",
            "OVERLAY_THRESHOLD",
            "MODELS_DIR",
            "MODEL_PATH",
            "CLASSES_FILE_PATH",
            "SHM_NAME",
        ):
            monkeypatch.delenv(var, raising=False)
        cfg = Config()
        assert cfg.CONFIDENCE_THRESHOLD == 0.75
        assert cfg.OVERLAY_THRESHOLD == 0.45
        assert cfg.MODELS_DIR == "/data/models"
        assert cfg.MODEL_PATH == os.path.join("/data/models", "weights.engine")
        assert cfg.DEFAULT_LABELS == ["CLASS1", "CLASS2", "CLASS3"]
        assert cfg.SHM_NAME == "conecsa_frame_shm"

    def test_classes_file_derived_from_model_base(self, monkeypatch):
        monkeypatch.setenv("MODEL_PATH", "/data/models/custom.engine")
        monkeypatch.delenv("CLASSES_FILE_PATH", raising=False)
        cfg = Config()
        assert cfg.CLASSES_FILE_PATH == "/data/models/custom.txt"

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("CONFIDENCE_THRESHOLD", "0.3")
        monkeypatch.setenv("OVERLAY_THRESHOLD", "0.6")
        monkeypatch.setenv("SHM_NAME", "other_shm")
        cfg = Config()
        assert cfg.CONFIDENCE_THRESHOLD == 0.3
        assert cfg.OVERLAY_THRESHOLD == 0.6
        assert cfg.SHM_NAME == "other_shm"


class TestSetOverlayThreshold:
    def test_accepts_in_range(self):
        cfg = Config()
        assert cfg.set_overlay_threshold(0.5) is True
        assert cfg.OVERLAY_THRESHOLD == 0.5

    def test_accepts_boundaries(self):
        cfg = Config()
        assert cfg.set_overlay_threshold(0.0) is True
        assert cfg.set_overlay_threshold(1.0) is True

    def test_rejects_out_of_range(self):
        cfg = Config()
        cfg.OVERLAY_THRESHOLD = 0.45
        assert cfg.set_overlay_threshold(1.5) is False
        assert cfg.set_overlay_threshold(-0.1) is False
        assert cfg.OVERLAY_THRESHOLD == 0.45
