"""Unit tests for TrainingService job-state handling and start() validation.

The trainer subprocess itself is not exercised: ``_run`` is stubbed out so
``start()`` stops at the state transition it owns (validation, single-job
lock, dataset freezing).
"""
from types import SimpleNamespace

import pytest

from service.dataset_service import DatasetError
from service.training_service import TrainingService


class FakeDataset:
    def __init__(self):
        self.frozen = False
        self.validated = 0

    def validate_for_training(self):
        self.validated += 1


class FakeRegistry:
    def __init__(self, dataset):
        self._dataset = dataset

    def get(self, dataset_id):
        return self._dataset


@pytest.fixture
def config():
    return SimpleNamespace(
        DEFAULT_EPOCHS=50,
        TRAIN_BATCH=4,
        DEFAULT_PATIENCE=10,
        BASE_WEIGHTS="/assets/yolo26s.pt",
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
