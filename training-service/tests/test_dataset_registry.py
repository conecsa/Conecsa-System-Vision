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
