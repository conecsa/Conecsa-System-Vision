"""Unit tests for the training-service config helpers and path properties."""
import pytest
from service.config import Config, _env_float, _env_int, parse_train_tile


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

    def test_stereo_combine_is_off_by_default(self, monkeypatch):
        # Blending halves the frame, which wrecks an ordinary camera's image,
        # so the seed must be off — only a 3D camera turns it on, from the UI.
        # Re-imported with the env cleared: the value is read at class creation.
        monkeypatch.delenv("STEREO_COMBINE", raising=False)
        import importlib

        import service.config as config_module

        reloaded = importlib.reload(config_module)
        assert reloaded.Config.STEREO_COMBINE == "none"


class TestTrainingKnobs:
    def _reload(self, monkeypatch, **env):
        import importlib

        import service.config as config_module

        for name in ("TRAIN_IMG_SIZE", "TRAIN_DATASET_IMG_SIZE", "TRAIN_OVERRIDES",
                     "TRAIN_TILE", "TRAIN_TILE_OVERLAP", "TRAIN_TILE_MIN_VISIBLE"):
            monkeypatch.delenv(name, raising=False)
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        return importlib.reload(config_module).Config

    def test_defaults_are_640_training_on_native_datasets(self, monkeypatch):
        cfg = self._reload(monkeypatch)
        assert cfg.IMG_SIZE == 640
        assert cfg.DATASET_IMG_SIZE == 0
        assert cfg.TRAIN_OVERRIDES == ""

    def test_default_geometry_is_auto_tiles(self, monkeypatch):
        cfg = self._reload(monkeypatch)
        assert cfg.TRAIN_TILE == "auto"
        assert cfg.TRAIN_TILE_OVERLAP == 0.2
        assert cfg.TRAIN_TILE_MIN_VISIBLE == 0.25

    def test_tile_env_overrides(self, monkeypatch):
        cfg = self._reload(monkeypatch, TRAIN_TILE="720", TRAIN_TILE_OVERLAP="0.3",
                           TRAIN_TILE_MIN_VISIBLE="0.5")
        assert (cfg.TRAIN_TILE, cfg.TRAIN_TILE_OVERLAP, cfg.TRAIN_TILE_MIN_VISIBLE) == (720, 0.3, 0.5)

    def test_out_of_range_fractions_fall_back(self, monkeypatch):
        cfg = self._reload(monkeypatch, TRAIN_TILE_OVERLAP="1.0", TRAIN_TILE_MIN_VISIBLE="0")
        assert (cfg.TRAIN_TILE_OVERLAP, cfg.TRAIN_TILE_MIN_VISIBLE) == (0.2, 0.25)

    def test_env_overrides(self, monkeypatch):
        cfg = self._reload(
            monkeypatch,
            TRAIN_IMG_SIZE="1280",
            TRAIN_DATASET_IMG_SIZE="640",
            TRAIN_OVERRIDES="freeze=10",
        )
        assert cfg.IMG_SIZE == 1280
        assert cfg.DATASET_IMG_SIZE == 640
        assert cfg.TRAIN_OVERRIDES == "freeze=10"


class TestParseTrainTile:
    @pytest.mark.parametrize("raw,expected", [
        (None, "auto"), ("", "auto"), ("auto", "auto"), (" Auto ", "auto"),
        ("off", None), ("0", None), ("none", None),
        ("720", 720), ("1080", 1080),
        ("abc", "auto"), ("-5", "auto"), ("7.5", "auto"),
    ])
    def test_values(self, raw, expected):
        assert parse_train_tile(raw) == expected
