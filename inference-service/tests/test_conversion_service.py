"""Unit tests for ConversionService pure helpers and job serialization."""
import time

import pytest
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
        assert job.imgsz is None
        assert isinstance(job.started_at, float)
        assert isinstance(job.started_monotonic, float)
        assert job.elapsed_secs >= 0.0


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
            "imgsz",
            "train_geometry",
            "started_at",
            "elapsed_secs",
        }

    def test_imgsz_is_serialized(self):
        pt_job = ConversionJob("j1", "m.pt", "/m.pt", "/m.onnx", "/m.engine", imgsz=1280)
        assert ConversionService.to_dict(pt_job)["imgsz"] == 1280
        # .onnx -> .engine-only jobs have no export size of their own.
        onnx_job = ConversionJob("j2", "m.onnx", "", "/m.onnx", "/m.engine")
        assert ConversionService.to_dict(onnx_job)["imgsz"] is None


class TestElapsedSecs:
    def test_is_measured_from_the_monotonic_clock(self):
        # The device has no RTC battery, so the hub steps CLOCK_REALTIME
        # whenever it notices drift — mid-conversion included. A job's age must
        # come from the monotonic clock, so a `started_at` that jumps (here to
        # the epoch) cannot move it.
        job = ConversionJob("j1", "m.pt", "/m.pt", "/m.onnx", "/m.engine")
        job.started_monotonic = time.monotonic() - 30.0
        job.started_at = 0.0

        assert job.elapsed_secs == pytest.approx(30.0, abs=1.0)
        assert ConversionService.to_dict(job)["elapsed_secs"] == pytest.approx(30.0, abs=1.0)

    def test_never_negative(self):
        job = ConversionJob("j1", "m.pt", "/m.pt", "/m.onnx", "/m.engine")
        job.started_monotonic = time.monotonic() + 100.0
        assert job.elapsed_secs == 0.0


class TestRemoveFileSafe:
    def test_removes_existing(self, tmp_path):
        f = tmp_path / "x.onnx"
        f.write_text("data")
        _remove_file_safe(str(f))
        assert not f.exists()

    def test_missing_file_is_noop(self, tmp_path):
        # Should not raise.
        _remove_file_safe(str(tmp_path / "absent.onnx"))


class TestStartPtConversion:
    def test_records_imgsz_on_the_job(self, monkeypatch, tmp_path):
        svc = ConversionService()
        # Keep the worker thread from touching torch/TensorRT.
        monkeypatch.setattr(ConversionService, "_run_job", lambda self, job_id: None)
        job = svc.start_pt_conversion(str(tmp_path / "m.pt"), "m.pt", str(tmp_path), imgsz=1280)
        assert job.imgsz == 1280
        assert svc.get_job(job.job_id) is job

    def test_records_the_declared_training_geometry(self, monkeypatch, tmp_path):
        svc = ConversionService()
        monkeypatch.setattr(ConversionService, "_run_job", lambda self, job_id: None)
        job = svc.start_pt_conversion(str(tmp_path / "m.pt"), "m.pt", str(tmp_path),
                                      imgsz=640, train_geometry="tiles:auto")
        assert job.train_geometry == "tiles:auto"
        assert svc.to_dict(job)["train_geometry"] == "tiles:auto"
        plain = svc.start_pt_conversion(str(tmp_path / "n.pt"), "n.pt", str(tmp_path))
        assert plain.train_geometry is None

    def test_onnx_only_job_has_no_imgsz(self, monkeypatch, tmp_path):
        svc = ConversionService()
        monkeypatch.setattr(ConversionService, "_run_job", lambda self, job_id: None)
        job = svc.start_onnx_conversion(str(tmp_path / "m.onnx"), "m.onnx", str(tmp_path))
        assert job.imgsz is None


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
