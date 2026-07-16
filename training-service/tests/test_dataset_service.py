"""Unit tests for DatasetService validation and on-disk CRUD."""
import json
from types import SimpleNamespace

import pytest
import yaml

from service.dataset_service import (
    Box,
    DatasetError,
    DatasetService,
    ImageEntry,
    NamedBox,
    validate_dataset_name,
)

_DATASET_ID = "0123abcd-4567-89ab-cdef-000000000000"


@pytest.fixture
def ds(tmp_path):
    return DatasetService(_DATASET_ID, str(tmp_path), config=None)


def _write_classes(tmp_path, classes):
    (tmp_path / "classes.json").write_text(json.dumps(classes))


class TestValidateDatasetName:
    def test_valid_name_is_stripped(self):
        assert validate_dataset_name("  My Dataset-1 ") == "My Dataset-1"

    def test_empty_rejected(self):
        with pytest.raises(DatasetError):
            validate_dataset_name("   ")
        with pytest.raises(DatasetError):
            # Callers are gRPC handlers, so a missing field can reach this as None:
            # assert it is rejected, not that the type checker forbids it.
            validate_dataset_name(None)  # pyright: ignore[reportArgumentType]

    def test_too_long_rejected(self):
        with pytest.raises(DatasetError):
            validate_dataset_name("x" * 65)

    def test_invalid_characters_rejected(self):
        for bad in ("has/slash", "dollar$", "semi;colon"):
            with pytest.raises(DatasetError):
                validate_dataset_name(bad)


class TestClassColorSuffix:
    """Class names may carry a "name #rrggbb" color; dataset names may not."""

    def test_add_class_accepts_a_hex_suffix(self, ds):
        assert ds.add_class("cap #ff0000") == ["cap #ff0000"]

    def test_class_names_still_reject_path_tricks(self, ds):
        for bad in ("has/slash", "dollar$", "semi;colon"):
            with pytest.raises(DatasetError):
                ds.add_class(bad)

    def test_dataset_names_still_reject_hash(self):
        with pytest.raises(DatasetError):
            validate_dataset_name("my #dataset")

    def test_data_yaml_keeps_the_color_suffix(self, tmp_path):
        # The '#' must survive as data, not be swallowed as a YAML comment —
        # build_split emits names as single-quoted scalars.
        cfg = SimpleNamespace(runs_dir=str(tmp_path / "runs"))
        svc = DatasetService(_DATASET_ID, str(tmp_path), config=cfg)
        svc.add_class("cap #ff0000")
        svc.add_class("bottle")
        for _ in range(2):
            entry = svc.add_image(b"img")
            svc.set_labels(entry.image_id, [Box(0, 0.5, 0.5, 0.2, 0.2)])

        yaml_path = svc.build_split("job-1")
        with open(yaml_path) as f:
            data = yaml.safe_load(f)

        assert data["nc"] == 2
        assert data["names"] == ["cap #ff0000", "bottle"]


class TestDataclasses:
    def test_box_fields(self):
        b = Box(1, 0.5, 0.5, 0.2, 0.3)
        assert (b.class_id, b.cx, b.cy, b.w, b.h) == (1, 0.5, 0.5, 0.2, 0.3)

    def test_image_entry_default_replica_false(self):
        e = ImageEntry("id", 1.0, labeled=True, box_count=2)
        assert e.replica is False


class TestCheckId:
    def test_valid_uuid_like_id(self):
        DatasetService._check_id(_DATASET_ID)  # no raise

    def test_rejects_bad_id(self):
        for bad in ("", "UPPER", "has space", "path/traversal"):
            with pytest.raises(DatasetError):
                DatasetService._check_id(bad)


class TestImageCrud:
    def test_add_then_get_roundtrip(self, ds):
        entry = ds.add_image(b"jpeg-bytes")
        assert isinstance(entry, ImageEntry)
        assert entry.labeled is False
        assert ds.get_image_bytes(entry.image_id) == b"jpeg-bytes"

    def test_list_images(self, ds):
        ds.add_image(b"a")
        ds.add_image(b"b")
        assert len(ds.list_images()) == 2

    def test_get_missing_image_raises(self, ds):
        with pytest.raises(DatasetError):
            ds.get_image_bytes("11111111-1111-1111-1111-111111111111")

    def test_delete_image(self, ds):
        entry = ds.add_image(b"a")
        ds.delete_image(entry.image_id)
        assert ds.list_images() == []

    def test_frozen_dataset_rejects_add(self, ds):
        ds.frozen = True
        with pytest.raises(DatasetError):
            ds.add_image(b"a")


class TestLabels:
    def test_set_and_get_labels_roundtrip(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap", "bottle"])
        entry = ds.add_image(b"img")
        boxes = [Box(0, 0.5, 0.5, 0.2, 0.2), Box(1, 0.1, 0.1, 0.05, 0.05)]
        ds.set_labels(entry.image_id, boxes)
        got = ds.get_labels(entry.image_id)
        assert len(got) == 2
        assert got[0].class_id == 0
        assert got[1].class_id == 1

    def test_unlabeled_image_returns_empty(self, ds):
        entry = ds.add_image(b"img")
        assert ds.get_labels(entry.image_id) == []

    def test_set_labels_rejects_unknown_class(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap"])
        entry = ds.add_image(b"img")
        with pytest.raises(DatasetError):
            ds.set_labels(entry.image_id, [Box(5, 0.5, 0.5, 0.2, 0.2)])

    def test_set_labels_rejects_out_of_range_coords(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap"])
        entry = ds.add_image(b"img")
        with pytest.raises(DatasetError):
            ds.set_labels(entry.image_id, [Box(0, 1.5, 0.5, 0.2, 0.2)])

    def test_empty_labels_removes_file(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap"])
        entry = ds.add_image(b"img")
        ds.set_labels(entry.image_id, [Box(0, 0.5, 0.5, 0.2, 0.2)])
        ds.set_labels(entry.image_id, [])
        assert ds.get_labels(entry.image_id) == []


class TestAddLabeledImage:
    def test_writes_image_and_labels(self, ds):
        entry = ds.add_labeled_image(b"img", [NamedBox("cap", 0.5, 0.5, 0.2, 0.2)])
        assert entry.labeled is True
        assert entry.box_count == 1
        assert ds.get_image_bytes(entry.image_id) == b"img"
        got = ds.get_labels(entry.image_id)
        assert len(got) == 1
        assert (got[0].cx, got[0].cy) == (0.5, 0.5)

    def test_missing_class_is_appended(self, ds):
        # No classes.json yet — the class list starts from this upload.
        ds.add_labeled_image(b"img", [NamedBox("cap", 0.5, 0.5, 0.2, 0.2)])
        assert ds.get_classes() == ["cap"]

    def test_existing_class_reused_by_index(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap", "bottle"])
        entry = ds.add_labeled_image(b"img", [NamedBox("bottle", 0.5, 0.5, 0.2, 0.2)])
        assert ds.get_classes() == ["cap", "bottle"]
        assert ds.get_labels(entry.image_id)[0].class_id == 1

    def test_mixed_known_and_new_classes(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap"])
        entry = ds.add_labeled_image(b"img", [
            NamedBox("box", 0.2, 0.2, 0.1, 0.1),
            NamedBox("cap", 0.5, 0.5, 0.2, 0.2),
            NamedBox("box", 0.8, 0.8, 0.1, 0.1),
        ])
        assert ds.get_classes() == ["cap", "box"]
        ids = [b.class_id for b in ds.get_labels(entry.image_id)]
        assert ids == [1, 0, 1]

    def test_invalid_class_name_fails_before_any_write(self, ds, tmp_path):
        _write_classes(tmp_path, ["cap"])
        with pytest.raises(DatasetError):
            ds.add_labeled_image(b"img", [
                NamedBox("cap", 0.5, 0.5, 0.2, 0.2),
                NamedBox("bad/name", 0.5, 0.5, 0.2, 0.2),
            ])
        assert ds.list_images() == []
        assert ds.get_classes() == ["cap"]

    def test_out_of_range_coords_fail_before_any_write(self, ds):
        with pytest.raises(DatasetError):
            ds.add_labeled_image(b"img", [NamedBox("cap", 1.5, 0.5, 0.2, 0.2)])
        assert ds.list_images() == []
        assert ds.get_classes() == []

    def test_frozen_dataset_rejects(self, ds):
        ds.frozen = True
        with pytest.raises(DatasetError):
            ds.add_labeled_image(b"img", [NamedBox("cap", 0.5, 0.5, 0.2, 0.2)])

    def test_empty_boxes_creates_unlabeled_entry(self, ds):
        entry = ds.add_labeled_image(b"img", [])
        assert entry.labeled is False
        assert entry.box_count == 0
        assert ds.get_labels(entry.image_id) == []
