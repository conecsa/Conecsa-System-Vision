"""Unit tests for the training-service config helpers and path properties."""
from service.config import Config, _env_float, _env_int


class TestEnvFloat:
    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("SOME_FLOAT", raising=False)
        assert _env_float("SOME_FLOAT", 0.5) == 0.5

    def test_parses_value(self, monkeypatch):
        monkeypatch.setenv("SOME_FLOAT", "1.25")
        assert _env_float("SOME_FLOAT", 0.5) == 1.25

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("SOME_FLOAT", "not-a-number")
        assert _env_float("SOME_FLOAT", 0.5) == 0.5


class TestEnvInt:
    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("SOME_INT", raising=False)
        assert _env_int("SOME_INT", 7) == 7

    def test_parses_value(self, monkeypatch):
        monkeypatch.setenv("SOME_INT", "42")
        assert _env_int("SOME_INT", 7) == 42

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("SOME_INT", "3.14")
        assert _env_int("SOME_INT", 7) == 7


class TestPathProperties:
    def test_derived_from_data_dir(self):
        cfg = Config()
        cfg.DATA_DIR = "/tmp/training"
        assert cfg.datasets_dir == "/tmp/training/datasets"
        assert cfg.runs_dir == "/tmp/training/runs"
        assert cfg.legacy_dataset_dir == "/tmp/training/dataset"

    def test_stereo_defaults_are_clamped(self):
        # Class-level clamping keeps the blend params in range.
        assert 0.0 <= Config.STEREO_BLEND_ALPHA <= 1.0
        assert -0.5 <= Config.STEREO_OFFSET <= 0.5
        assert -0.5 <= Config.STEREO_OFFSET_Y <= 0.5
