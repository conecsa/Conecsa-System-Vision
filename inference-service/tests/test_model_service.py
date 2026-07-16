"""Unit tests for ModelService path helpers and validation."""
from api.config import Config
from api.services.model_service import ModelService


class TestSiblingPathHelpers:
    def test_classes_file_for_model(self):
        assert (
            ModelService.classes_file_for_model("/data/models/weights.engine")
            == "/data/models/weights.txt"
        )

    def test_areas_file_for_model(self):
        assert (
            ModelService.areas_file_for_model("/data/models/weights.engine")
            == "/data/models/weights.areas.json"
        )

    def test_settings_file_for_model(self):
        assert (
            ModelService.settings_file_for_model("/data/models/weights.engine")
            == "/data/models/weights.settings.json"
        )

    def test_handles_other_extensions(self):
        assert ModelService.classes_file_for_model("/m/model.onnx") == "/m/model.txt"


class TestModelFilePath:
    def _svc(self, tmp_path):
        return ModelService(Config(), str(tmp_path))

    def test_valid_existing_model(self, tmp_path):
        svc = self._svc(tmp_path)
        (tmp_path / "weights.engine").write_bytes(b"x")
        assert svc.model_file_path("weights.engine") == str(tmp_path / "weights.engine")

    def test_missing_file_returns_empty(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc.model_file_path("absent.engine") == ""

    def test_path_traversal_rejected(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc.model_file_path("../weights.engine") == ""
        assert svc.model_file_path("/etc/passwd") == ""

    def test_disallowed_extension_rejected(self, tmp_path):
        svc = self._svc(tmp_path)
        (tmp_path / "notes.txt").write_text("x")
        assert svc.model_file_path("notes.txt") == ""

    def test_control_characters_rejected(self, tmp_path):
        svc = self._svc(tmp_path)
        assert svc.model_file_path("weights\n.engine") == ""


class TestDeleteModel:
    def test_cannot_delete_active_model(self, tmp_path):
        svc = ModelService(Config(), str(tmp_path))
        # current_model defaults to weights.engine
        ok, msg = svc.delete_model("weights.engine")
        assert ok is False
        assert "active" in msg

    def test_delete_missing_model(self, tmp_path):
        svc = ModelService(Config(), str(tmp_path))
        ok, msg = svc.delete_model("other.engine")
        assert ok is False
        assert "not found" in msg

    def test_delete_existing_model(self, tmp_path):
        svc = ModelService(Config(), str(tmp_path))
        (tmp_path / "other.engine").write_bytes(b"x")
        ok, msg = svc.delete_model("other.engine")
        assert ok is True
        assert not (tmp_path / "other.engine").exists()


class TestSaveModel:
    class _FakeUpload:
        def save(self, path):
            with open(path, "wb") as f:
                f.write(b"model-bytes")

    def test_rejects_bad_extension(self, tmp_path):
        svc = ModelService(Config(), str(tmp_path))
        ok, path, err = svc.save_model("bad.txt", self._FakeUpload())
        assert ok is False
        assert path == ""
        assert "Invalid file type" in err

    def test_saves_valid_model(self, tmp_path):
        svc = ModelService(Config(), str(tmp_path))
        ok, path, err = svc.save_model("m.onnx", self._FakeUpload())
        assert ok is True
        assert err == ""
        assert (tmp_path / "m.onnx").read_bytes() == b"model-bytes"
