"""Unit tests for ConversionService pure helpers and job serialization."""
from api.services.conversion_service import (
    ConversionJob,
    ConversionService,
    ConversionStatus,
    _remove_file_safe,
)


class TestConversionStatus:
    def test_string_enum_values(self):
        assert ConversionStatus.PENDING.value == "pending"
        assert ConversionStatus.CONVERTING_TO_ONNX.value == "converting_to_onnx"
        assert ConversionStatus.CONVERTING_TO_ENGINE.value == "converting_to_engine"
        assert ConversionStatus.DONE.value == "done"
        assert ConversionStatus.FAILED.value == "failed"

    def test_is_str_subclass(self):
        assert ConversionStatus.DONE == "done"


class TestConversionJobDefaults:
    def test_defaults(self):
        job = ConversionJob(
            job_id="j1",
            original_filename="m.pt",
            pt_path="/m.pt",
            onnx_path="/m.onnx",
            engine_path="/m.engine",
        )
        assert job.status is ConversionStatus.PENDING
        assert job.progress == 0
        assert job.error is None
        assert job.engine_filename is None
        assert isinstance(job.started_at, float)


class TestToDict:
    def test_serializes_status_value(self):
        job = ConversionJob("j1", "m.pt", "/m.pt", "/m.onnx", "/m.engine")
        job.status = ConversionStatus.CONVERTING_TO_ENGINE
        job.progress = 45
        d = ConversionService.to_dict(job)
        assert d["job_id"] == "j1"
        assert d["status"] == "converting_to_engine"  # .value, not the enum
        assert d["progress"] == 45
        assert set(d.keys()) == {
            "job_id",
            "original_filename",
            "status",
            "progress",
            "message",
            "error",
            "engine_filename",
            "started_at",
        }


class TestRemoveFileSafe:
    def test_removes_existing(self, tmp_path):
        f = tmp_path / "x.onnx"
        f.write_text("data")
        _remove_file_safe(str(f))
        assert not f.exists()

    def test_missing_file_is_noop(self, tmp_path):
        # Should not raise.
        _remove_file_safe(str(tmp_path / "absent.onnx"))


class TestJobRegistry:
    def test_get_unknown_job(self):
        svc = ConversionService()
        assert svc.get_job("nope") is None

    def test_active_jobs_excludes_terminal(self):
        svc = ConversionService()
        active = ConversionJob("a", "a.pt", "", "", "")
        done = ConversionJob("b", "b.pt", "", "", "")
        done.status = ConversionStatus.DONE
        failed = ConversionJob("c", "c.pt", "", "", "")
        failed.status = ConversionStatus.FAILED
        svc._jobs = {"a": active, "b": done, "c": failed}
        ids = {j.job_id for j in svc.get_active_jobs()}
        assert ids == {"a"}
