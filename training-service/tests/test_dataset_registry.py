"""Unit tests for DatasetRegistry lifecycle (create/list/get/delete)."""
import pytest
from service.config import Config
from service.dataset_registry import DatasetRegistry
from service.dataset_service import DatasetError


@pytest.fixture
def registry(tmp_path):
    cfg = Config()
    cfg.DATA_DIR = str(tmp_path)
    return DatasetRegistry(cfg, event_service=None)


class TestCheckId:
    def test_rejects_invalid_id(self):
        for bad in ("", "UPPER", "has space"):
            with pytest.raises(DatasetError):
                DatasetRegistry._check_id(bad)


class TestCreateListGet:
    def test_create_then_list(self, registry):
        meta = registry.create("My Dataset")
        assert meta["name"] == "My Dataset"
        listed = registry.list()
        assert len(listed) == 1
        assert listed[0]["dataset_id"] == meta["dataset_id"]

    def test_get_returns_service(self, registry):
        meta = registry.create("D1")
        ds = registry.get(meta["dataset_id"])
        assert ds.dataset_id == meta["dataset_id"]

    def test_get_unknown_raises(self, registry):
        with pytest.raises(DatasetError):
            registry.get("11111111-1111-1111-1111-111111111111")

    def test_create_rejects_invalid_name(self, registry):
        with pytest.raises(DatasetError):
            registry.create("bad/name")


class TestRenameDelete:
    def test_rename(self, registry):
        meta = registry.create("Old")
        renamed = registry.rename(meta["dataset_id"], "New")
        assert renamed["name"] == "New"

    def test_delete(self, registry):
        meta = registry.create("Doomed")
        registry.delete(meta["dataset_id"])
        assert registry.list() == []

    def test_delete_unknown_raises(self, registry):
        with pytest.raises(DatasetError):
            registry.delete("11111111-1111-1111-1111-111111111111")


class TestReloadFromDisk:
    def test_datasets_rescanned_by_new_registry(self, tmp_path):
        cfg = Config()
        cfg.DATA_DIR = str(tmp_path)
        r1 = DatasetRegistry(cfg, event_service=None)
        r1.create("Persisted")
        # A fresh registry over the same data dir rescans the dataset.
        r2 = DatasetRegistry(cfg, event_service=None)
        assert len(r2.list()) == 1
        assert r2.list()[0]["name"] == "Persisted"


class TestGeometry:
    def _registry(self, tmp_path, dataset_img_size):
        cfg = Config()
        cfg.DATA_DIR = str(tmp_path)
        cfg.DATASET_IMG_SIZE = dataset_img_size
        return DatasetRegistry(cfg, event_service=None)

    def test_default_config_creates_native_datasets(self, registry):
        meta = registry.create("Native")
        assert registry.get(meta["dataset_id"]).geometry() == {"native": True}
        assert registry.get(meta["dataset_id"]).info()["geometry"] == {"native": True}

    def test_letterbox_config_creates_letterbox_640_datasets(self, tmp_path):
        reg = self._registry(tmp_path, 640)
        meta = reg.create("Boxed")
        assert reg.get(meta["dataset_id"]).geometry() == {"letterbox": 640}

    def test_guard_refuses_a_dataset_from_the_other_geometry(self, tmp_path):
        boxed = self._registry(tmp_path, 640).create("Boxed")
        native_reg = self._registry(tmp_path, 0)
        with pytest.raises(DatasetError, match="TRAIN_DATASET_IMG_SIZE=640"):
            native_reg.get(boxed["dataset_id"]).check_geometry(
                native_reg._config.DATASET_IMG_SIZE)
        fresh = native_reg.create("Native")
        native_reg.get(fresh["dataset_id"]).check_geometry(0)

    def test_legacy_migration_records_letterbox_640_even_in_native_mode(self, tmp_path):
        cfg = Config()
        cfg.DATA_DIR = str(tmp_path)
        cfg.DATASET_IMG_SIZE = 0
        legacy = tmp_path / "dataset"
        (legacy / "images").mkdir(parents=True)
        (legacy / "labels").mkdir()
        reg = DatasetRegistry(cfg, event_service=None)
        (meta,) = reg.list()
        assert meta["name"] == "Default"
        assert reg.get(meta["dataset_id"]).geometry() == {"letterbox": 640}

    def test_import_uses_the_dataset_geometry_not_the_model_size(self, tmp_path,
                                                                 monkeypatch):
        import zipfile

        import cv2
        import numpy as np
        from service import dataset_registry

        seen = {}

        def fake_import(zip_path, dest_dir, img_size=640, max_total_mb=512):
            seen["img_size"] = img_size
            import os
            os.makedirs(os.path.join(dest_dir, "images"), exist_ok=True)
            os.makedirs(os.path.join(dest_dir, "labels"), exist_ok=True)
            return ["cap"], 0

        monkeypatch.setattr(dataset_registry, "import_dataset_zip", fake_import)
        cfg = Config()
        cfg.DATA_DIR = str(tmp_path)
        cfg.IMG_SIZE = 1280
        cfg.DATASET_IMG_SIZE = 0
        reg = DatasetRegistry(cfg, event_service=None)
        zip_path = tmp_path / "ds.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            ok, buf = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
            assert ok
            z.writestr("images/a.jpg", buf.tobytes())
        meta = reg.import_zip("Imported", str(zip_path))
        assert seen["img_size"] == 0
        assert reg.get(meta["dataset_id"]).geometry() == {"native": True}


class TestFreezeDeleteRace:
    """One lock owns the frozen transition (REFACTORING.md M4): a delete can
    never interleave between a job validating a dataset and freezing it."""

    def test_a_frozen_dataset_cannot_be_deleted(self, registry):
        meta = registry.create("D1")
        registry.freeze(meta["dataset_id"])
        with pytest.raises(DatasetError, match="locked"):
            registry.delete(meta["dataset_id"])
        # Still listed and intact.
        assert registry.get(meta["dataset_id"]) is not None

    def test_release_reopens_deletion(self, registry):
        meta = registry.create("D1")
        ds = registry.freeze(meta["dataset_id"])
        registry.release(ds)
        registry.delete(meta["dataset_id"])
        with pytest.raises(DatasetError):
            registry.get(meta["dataset_id"])

    def test_a_deleted_dataset_cannot_be_frozen(self, registry):
        meta = registry.create("D1")
        registry.delete(meta["dataset_id"])
        with pytest.raises(DatasetError, match="not found"):
            registry.freeze(meta["dataset_id"])

    def test_double_freeze_is_refused(self, registry):
        meta = registry.create("D1")
        registry.freeze(meta["dataset_id"])
        with pytest.raises(DatasetError, match="locked"):
            registry.freeze(meta["dataset_id"])

    def test_concurrent_freeze_and_delete_never_both_succeed(self, registry):
        import threading

        for _ in range(20):
            meta = registry.create("D1")
            dataset_id = meta["dataset_id"]
            barrier = threading.Barrier(2)
            outcomes = {}

            def freeze(dataset_id=dataset_id, barrier=barrier, outcomes=outcomes):
                barrier.wait()
                try:
                    registry.freeze(dataset_id)
                    outcomes["freeze"] = True
                except DatasetError:
                    outcomes["freeze"] = False

            def delete(dataset_id=dataset_id, barrier=barrier, outcomes=outcomes):
                barrier.wait()
                try:
                    registry.delete(dataset_id)
                    outcomes["delete"] = True
                except DatasetError:
                    outcomes["delete"] = False

            threads = [threading.Thread(target=freeze),
                       threading.Thread(target=delete)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)

            assert outcomes["freeze"] != outcomes["delete"], \
                "exactly one of freeze/delete may win"
            if outcomes["freeze"]:
                # The dataset survived; its directory must still exist for
                # the training job that claimed it.
                ds = registry.get(dataset_id)
                import os
                assert os.path.isdir(ds.root)
                registry.release(ds)
                registry.delete(dataset_id)

    def test_a_failed_rmtree_is_reported(self, registry, monkeypatch):
        import shutil as _shutil
        meta = registry.create("D1")

        def boom(path):
            raise OSError("file is busy")

        monkeypatch.setattr(_shutil, "rmtree", boom)
        with pytest.raises(DatasetError, match="could not be deleted"):
            registry.delete(meta["dataset_id"])
