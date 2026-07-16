"""Unit tests for DetectionAreaService (JSON-persisted, in normalized coords)."""
import json

import pytest

from api.services.detection_area_service import (
    DetectionArea,
    DetectionAreaService,
    MIN_SIZE,
    _clamp,
)


@pytest.fixture
def svc(tmp_path):
    return DetectionAreaService(str(tmp_path / "areas.json"))


class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5, 0.0, 1.0) == 0.5

    def test_below_and_above(self):
        assert _clamp(-1.0, 0.0, 1.0) == 0.0
        assert _clamp(2.0, 0.0, 1.0) == 1.0


class TestDetectionAreaDataclass:
    def test_to_dict_roundtrip(self):
        area = DetectionArea("a1", 0.1, 0.2, 0.3, 0.4, is_editing=True, shape="circle")
        d = area.to_dict()
        assert d["id"] == "a1"
        assert d["shape"] == "circle"
        assert d["is_editing"] is True
        assert d["width"] == 0.3


class TestAddAndList:
    def test_add_returns_editing_area_and_persists(self, svc, tmp_path):
        area = svc.add()
        assert area.is_editing is True
        assert area.label == "#1"
        assert len(svc.list()) == 1
        # File written to disk.
        raw = json.loads((tmp_path / "areas.json").read_text())
        assert len(raw["areas"]) == 1

    def test_second_add_demotes_first(self, svc):
        first = svc.add()
        svc.add()
        areas = {a.id: a for a in svc.list()}
        assert areas[first.id].is_editing is False

    def test_relabel_is_sequential(self, svc):
        svc.add()
        svc.add()
        labels = sorted(a.label for a in svc.list())
        assert labels == ["#1", "#2"]


class TestDeleteSaveEditDiscard:
    def test_delete_removes(self, svc):
        area = svc.add()
        deleted = svc.delete(area.id)
        assert deleted is True
        assert svc.list() == []

    def test_delete_unknown_returns_false(self, svc):
        deleted = svc.delete("nope")
        assert deleted is False

    def test_save_clears_editing(self, svc):
        area = svc.add()
        saved = svc.save(area.id)
        assert saved is not None
        assert saved.is_editing is False

    def test_edit_promotes_area(self, svc):
        area = svc.add()
        svc.save(area.id)
        edited = svc.edit(area.id)
        assert edited.is_editing is True

    def test_discard_new_area_removes_it(self, svc):
        area = svc.add()  # newly added, no snapshot
        discarded = svc.discard(area.id)
        assert discarded is True
        assert svc.list() == []

    def test_discard_restores_snapshot(self, svc):
        area = svc.add()
        svc.save(area.id)
        svc.edit(area.id)  # snapshots geometry
        svc.apply_command(area.id, "move_right")
        moved_x = next(a.x for a in svc.list() if a.id == area.id)
        svc.discard(area.id)
        restored_x = next(a.x for a in svc.list() if a.id == area.id)
        assert restored_x == pytest.approx(0.3)
        assert moved_x != pytest.approx(0.3)


class TestSetShape:
    def test_valid_shape(self, svc):
        area = svc.add()
        assert svc.set_shape(area.id, "circle").shape == "circle"

    def test_invalid_shape_rejected(self, svc):
        area = svc.add()
        assert svc.set_shape(area.id, "triangle") is None


class TestApplyCommand:
    def test_invalid_action(self, svc):
        area = svc.add()
        assert svc.apply_command(area.id, "teleport") is None

    def test_move_right_increases_x(self, svc):
        area = svc.add()
        before = area.x
        moved = svc.apply_command(area.id, "move_right")
        assert moved.x > before

    def test_shrink_respects_min_size(self, svc):
        area = svc.add()
        for _ in range(50):
            svc.apply_command(area.id, "shrink")
        final = next(a for a in svc.list() if a.id == area.id)
        assert final.width >= MIN_SIZE
        assert final.height >= MIN_SIZE

    def test_move_clamped_within_frame(self, svc):
        area = svc.add()
        for _ in range(100):
            svc.apply_command(area.id, "move_right")
        final = next(a for a in svc.list() if a.id == area.id)
        assert final.x + final.width <= 1.0 + 1e-9


class TestPersistenceReload:
    def test_areas_reload_from_disk(self, tmp_path):
        path = str(tmp_path / "areas.json")
        svc1 = DetectionAreaService(path)
        area = svc1.add()
        svc1.save(area.id)
        # A fresh service reads the same file back.
        svc2 = DetectionAreaService(path)
        reloaded = svc2.list()
        assert len(reloaded) == 1
        assert reloaded[0].is_editing is False  # persisted areas are not editing
        assert reloaded[0].label == "#1"
