"""Unit tests for TrainingService job-state handling and start() validation.

The trainer subprocess itself is not exercised: ``_run`` is stubbed out so
``start()`` stops at the state transition it owns (validation, single-job
lock, dataset freezing).
"""
from types import SimpleNamespace

import pytest
from service.dataset_service import DatasetError
from service.training_service import TrainingService, build_trainer_argv


class FakeDataset:
    def __init__(self, geometry="tiles:auto"):
        self.frozen = False
        self.validated = 0
        self.split_calls = []
        self.geometry = geometry

    def validate_for_training(self):
        self.validated += 1

    def build_split(self, job_id, **kwargs):
        from service.dataset_service import SplitResult
        from service.tile_split import TileSplitStats
        self.split_calls.append(kwargs)
        return SplitResult(f"/runs/{job_id}/dataset/data.yaml", 4, 2, self.geometry,
                           TileSplitStats())


class FakeRegistry:
    def __init__(self, dataset):
        self._dataset = dataset

    def get(self, dataset_id):
        return self._dataset

    def freeze(self, dataset_id):
        from service.dataset_service import DatasetError
        if self._dataset.frozen:
            raise DatasetError("Dataset is locked while a training job is running")
        self._dataset.frozen = True
        return self._dataset

    def release(self, ds):
        ds.frozen = False


@pytest.fixture
def config(tmp_path):
    return SimpleNamespace(
        DEFAULT_EPOCHS=50,
        TRAIN_BATCH=4,
        DEFAULT_PATIENCE=10,
        BASE_WEIGHTS="/assets/yolo26s.pt",
        IMG_SIZE=640,
        TRAIN_WORKERS=0,
        TRAIN_AMP=True,
        TRAIN_OVERRIDES="",
        TRAIN_TILE="auto",
        TRAIN_TILE_OVERLAP=0.2,
        TRAIN_TILE_MIN_VISIBLE=0.25,
        TRAIN_TIMEOUT_SEC=0,
        TRAIN_STALL_TIMEOUT_SEC=3600,
        GATEWAY_ADDR="http://gateway.test:5000",
        runs_dir=str(tmp_path / "runs"),
    )


@pytest.fixture
def dataset():
    return FakeDataset()


@pytest.fixture
def svc(config, dataset, monkeypatch):
    # Keep start() from launching the real trainer subprocess.
    monkeypatch.setattr(TrainingService, "_run", lambda self, *a, **k: None)
    return TrainingService(config, FakeRegistry(dataset))  # pyright: ignore[reportArgumentType]


class TestInitialState:
    def test_starts_idle_and_inactive(self, svc):
        assert svc.get_job().status == "idle"
        assert svc.is_active() is False

    def test_get_job_returns_a_copy(self, svc):
        job = svc.get_job()
        job.status = "training"
        assert svc.get_job().status == "idle"

    def test_cancel_and_finish_early_require_a_running_job(self, svc):
        assert svc.cancel() is False
        assert svc.finish_early() is False


class TestStartValidation:
    def test_epochs_out_of_range_is_rejected(self, svc):
        with pytest.raises(DatasetError, match="Epochs"):
            svc.start("d1", "my-model", epochs=1001)

    def test_invalid_model_name_is_rejected(self, svc):
        with pytest.raises(DatasetError):
            svc.start("d1", "")

    def test_initial_weights_require_a_weights_store(self, svc):
        with pytest.raises(DatasetError, match="Weights store"):
            svc.start("d1", "my-model", initial_weights_id="w1")


class TestStart:
    def test_successful_start_prepares_the_job(self, svc, dataset, config):
        job = svc.start("d1", "my-model")
        assert job.status == "preparing"
        assert job.model_name == "my-model"
        assert job.dataset_id == "d1"
        assert job.total_epochs == config.DEFAULT_EPOCHS
        assert job.federated is False
        assert svc.is_active() is True
        assert dataset.validated == 1
        assert dataset.frozen is True

    def test_only_one_job_at_a_time(self, svc):
        svc.start("d1", "my-model")
        with pytest.raises(DatasetError, match="already running"):
            svc.start("d1", "other-model")

    def test_federated_blank_name_becomes_a_label(self, svc):
        job = svc.start("d1", "", federated=True)
        assert job.model_name == "federated"
        assert job.federated is True

    def test_explicit_epochs_override_the_default(self, svc):
        assert svc.start("d1", "my-model", epochs=7).total_epochs == 7


class TestTrainerArgv:
    def test_default_argv_matches_the_640_contract(self, config):
        cmd = build_trainer_argv(config, "/d/data.yaml", "/assets/yolo26s.pt",
                                 epochs=50, patience=10, batch=4, job_id="job1")
        assert cmd[1:3] == ["-m", "service._yolo_trainer"]
        assert cmd[cmd.index("--imgsz") + 1] == "640"
        assert "--override" not in cmd
        assert "--no-amp" not in cmd

    def test_imgsz_and_overrides_are_forwarded(self, config):
        config.IMG_SIZE = 1280
        config.TRAIN_AMP = False
        config.TRAIN_OVERRIDES = "freeze=10 lr0=0.002"
        cmd = build_trainer_argv(config, "/d/data.yaml", "/w.pt",
                                 epochs=20, patience=10, batch=4, job_id="job1")
        assert cmd[cmd.index("--imgsz") + 1] == "1280"
        assert "--no-amp" in cmd
        pairs = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "--override"]
        assert pairs == ["freeze=10", "lr0=0.002"]

    def test_start_rejects_invalid_overrides_before_freezing(self, svc, config, dataset):
        config.TRAIN_OVERRIDES = "imgsz=1280"
        with pytest.raises(DatasetError, match="TRAIN_OVERRIDES"):
            svc.start("ds", "model-a")
        assert dataset.frozen is False


class FakeProcess:
    """A trainer that prints one ``done`` line and exits 0."""

    def __init__(self, best="/runs/job/weights/best.pt"):
        import json
        self.stdout = iter([json.dumps({"done": True, "best": best}) + "\n"])
        self.stderr = iter([])
        self.returncode = 0
        self.pid = 4242

    def poll(self):
        return 0

    def wait(self):
        return 0


class TestRun:
    """``_run`` with the subprocess, upload and event plumbing faked."""

    @pytest.fixture
    def running(self, config, dataset, monkeypatch):
        import service.training_service as ts
        monkeypatch.setattr(ts.subprocess, "Popen", lambda *a, **k: FakeProcess())
        uploads = []
        monkeypatch.setattr(TrainingService, "_upload_best",
                            lambda self, best: uploads.append(best) or "conv-1")
        svc = TrainingService(config, FakeRegistry(dataset))  # pyright: ignore[reportArgumentType]
        # Drive the job through start() so _job_dataset and the job state are real.
        monkeypatch.setattr(TrainingService, "_run", lambda self, *a, **k: None)
        svc.start("d1", "my-model")
        monkeypatch.undo()  # restore the real _run (Popen/upload stay patched below)
        monkeypatch.setattr(ts.subprocess, "Popen", lambda *a, **k: FakeProcess())
        monkeypatch.setattr(TrainingService, "_upload_best",
                            lambda self, best: uploads.append(best) or "conv-1")
        return svc, uploads

    def test_split_uses_the_config_tile_knobs_and_records_the_geometry(
            self, running, dataset, config):
        svc, uploads = running
        job = svc.get_job()
        svc._run(job.job_id, epochs=1, batch=4, patience=10, weights_path="/w.pt")
        assert dataset.split_calls == [{"tile": "auto", "overlap": 0.2, "min_visible": 0.25}]
        done = svc.get_job()
        assert done.status == "done" and done.geometry == "tiles:auto"
        assert uploads == ["/runs/job/weights/best.pt"]

    def test_tile_off_is_forwarded(self, running, dataset, config):
        svc, _ = running
        config.TRAIN_TILE = None
        svc._run(svc.get_job().job_id, epochs=1, batch=4, patience=10, weights_path="/w.pt")
        assert dataset.split_calls[0]["tile"] is None

    def test_the_materialised_split_is_removed_after_the_run(self, running, config, tmp_path):
        svc, _ = running
        job_id = svc.get_job().job_id
        scratch = tmp_path / "runs" / job_id / "dataset" / "train" / "images"
        scratch.mkdir(parents=True)
        (scratch / "a_t0.jpg").write_bytes(b"jpg")
        (tmp_path / "runs" / job_id / "weights").mkdir(parents=True)
        (tmp_path / "runs" / job_id / "weights" / "best.pt").write_bytes(b"pt")
        svc._run(job_id, epochs=1, batch=4, patience=10, weights_path="/w.pt")
        assert not (tmp_path / "runs" / job_id / "dataset").exists()
        assert (tmp_path / "runs" / job_id / "weights" / "best.pt").exists()


class TestUploadBest:
    def test_posts_imgsz_and_the_effective_geometry(self, config, dataset, monkeypatch, tmp_path):
        import service.training_service as ts
        posted = {}

        def fake_post(url, files, data, timeout):
            posted.update(url=url, filename=files["file"][0], data=data)
            return SimpleNamespace(status_code=202, json=lambda: {"job_id": "conv-7"})

        monkeypatch.setattr(ts.requests, "post", fake_post)
        svc = TrainingService(config, FakeRegistry(dataset))  # pyright: ignore[reportArgumentType]
        svc._job.model_name = "my-model"
        svc._job.geometry = "tiles:auto"
        best = tmp_path / "best.pt"
        best.write_bytes(b"pt")
        assert svc._upload_best(str(best)) == "conv-7"
        assert posted["url"] == "http://gateway.test:5000/api/v1/model"
        assert posted["filename"] == "my-model.pt"
        assert posted["data"] == {"imgsz": "640", "train_geometry": "tiles:auto"}
