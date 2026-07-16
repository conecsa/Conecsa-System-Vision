"""Unit tests for the gateway Settings and _env_float helper."""
from gateway.config import Settings, _env_float


class TestEnvFloat:
    def test_missing_returns_default(self, monkeypatch):
        monkeypatch.delenv("SOME_FLOAT", raising=False)
        assert _env_float("SOME_FLOAT", 0.5) == 0.5

    def test_parses_value(self, monkeypatch):
        monkeypatch.setenv("SOME_FLOAT", "2.5")
        assert _env_float("SOME_FLOAT", 0.5) == 2.5

    def test_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("SOME_FLOAT", "abc")
        assert _env_float("SOME_FLOAT", 0.5) == 0.5


class TestSettingsDefaults:
    def test_grpc_peer_defaults(self):
        assert Settings.INFERENCE_GRPC_ADDR == "inference-service:50061"
        assert Settings.HARDWARE_AGENT_ADDR == "os:50051"
        assert Settings.TRAINING_GRPC_ADDR == "training-service:50071"

    def test_shm_names(self):
        assert Settings.CAMERA_SHM_NAME == "conecsa_frame_shm"
        assert Settings.PROCESSED_SHM_NAME == "conecsa_processed_shm"

    def test_numeric_settings_have_expected_types(self):
        assert isinstance(Settings.PORT, int)
        assert isinstance(Settings.WAITRESS_THREADS, int)
        assert isinstance(Settings.GRPC_TIMEOUT, float)
