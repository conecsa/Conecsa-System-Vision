"""Unit tests for DatasetService validation and on-disk CRUD."""
import json
from types import SimpleNamespace

import pytest
import yaml
from service.dataset_service import (
    LEGACY_GEOMETRY,
    Box,
    DatasetError,
    DatasetService,
    ImageEntry,
    NamedBox,
    geometry_for,
    normalize_geometry,
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

        result = svc.build_split("job-1")
        assert result.geometry == "frames"
        with open(result.yaml_path) as f:
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


class TestMetaCorruptionIsReported:
    def test_corrupt_meta_is_quarantined_not_silently_empty(self, tmp_path,
                                                            caplog):
        import logging as _logging

        from service.config import Config
        from service.dataset_service import DatasetService

        root = tmp_path / "ds"
        ds = DatasetService("11111111-1111-1111-1111-111111111111",
                            str(root), Config())
        ds.write_meta("D1")
        meta_file = root / "meta.json"
        meta_file.write_text('{"trunc')

        with caplog.at_level(_logging.ERROR):
            ds.meta()
        assert (root / "meta.json.corrupt").exists(), "evidence must survive"
        assert any("corrupt" in r.message for r in caplog.records)


class TestGeometryHelpers:
    def test_geometry_for_size(self):
        assert geometry_for(640) == {"letterbox": 640}
        assert geometry_for(1280) == {"letterbox": 1280}
        assert geometry_for(0) == {"native": True}
        assert geometry_for(-1) == {"native": True}

    def test_normalize_unknown_values_fall_back_to_legacy(self):
        for bad in (None, {}, [], "native", {"letterbox": "x"}, {"letterbox": 0},
                    {"native": False}):
            assert normalize_geometry(bad) == LEGACY_GEOMETRY
        assert normalize_geometry({"native": True, "letterbox": 640}) == {"native": True}
        assert normalize_geometry({"letterbox": "1280"}) == {"letterbox": 1280}


class TestDatasetGeometry:
    def _ds(self, tmp_path, name="ds"):
        return DatasetService(_DATASET_ID, str(tmp_path / name),
                              config=SimpleNamespace(MIN_IMAGES=20))

    def test_write_meta_records_the_given_geometry(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("Native", geometry={"native": True})
        meta = json.loads((tmp_path / "ds" / "meta.json").read_text())
        assert meta["geometry"] == {"native": True}
        assert ds.geometry() == {"native": True}
        assert ds.info()["geometry"] == {"native": True}

    def test_write_meta_without_geometry_records_legacy_letterbox(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("Default")
        meta = json.loads((tmp_path / "ds" / "meta.json").read_text())
        assert meta["geometry"] == {"letterbox": 640}

    def test_geometry_is_fixed_at_creation(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("D", geometry={"letterbox": 640})
        ds.write_meta("D renamed", geometry={"native": True})
        assert ds.geometry() == {"letterbox": 640}

    def test_legacy_meta_without_key_reads_as_letterbox_640(self, tmp_path):
        root = tmp_path / "ds"
        root.mkdir()
        (root / "meta.json").write_text(
            json.dumps({"name": "Old", "created_at": 1.0, "cover_image_id": ""}))
        ds = self._ds(tmp_path)
        assert ds.geometry() == {"letterbox": 640}
        ds.check_geometry(640)  # must not raise
        with pytest.raises(DatasetError, match="640×640 letterboxed"):
            ds.check_geometry(0)

    def test_legacy_meta_is_backfilled_on_the_next_save(self, tmp_path):
        root = tmp_path / "ds"
        root.mkdir()
        (root / "meta.json").write_text(
            json.dumps({"name": "Old", "created_at": 1.0, "cover_image_id": ""}))
        ds = self._ds(tmp_path)
        ds.rename("Still old")
        meta = json.loads((root / "meta.json").read_text())
        assert meta["geometry"] == {"letterbox": 640}
        assert meta["name"] == "Still old"

    def test_check_geometry_accepts_a_match(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("Native", geometry={"native": True})
        ds.check_geometry(0)
        ds.write_meta("Boxed", geometry={"letterbox": 640})  # different dataset
        self._ds(tmp_path, "other").write_meta("Boxed", geometry={"letterbox": 640})
        self._ds(tmp_path, "other").check_geometry(640)

    def test_check_geometry_rejects_letterbox_dataset_in_native_mode(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("Shop floor", geometry={"letterbox": 640})
        with pytest.raises(DatasetError) as exc:
            ds.check_geometry(0)
        msg = str(exc.value)
        assert "Shop floor" in msg
        assert "640×640 letterboxed images" in msg
        assert "TRAIN_DATASET_IMG_SIZE=640" in msg
        assert "create a new dataset" in msg

    def test_check_geometry_rejects_native_dataset_in_letterbox_mode(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("Hi-res", geometry={"native": True})
        with pytest.raises(DatasetError) as exc:
            ds.check_geometry(640)
        msg = str(exc.value)
        assert "native-resolution images" in msg
        assert "TRAIN_DATASET_IMG_SIZE=0" in msg

    def test_check_geometry_rejects_a_different_square(self, tmp_path):
        ds = self._ds(tmp_path)
        ds.write_meta("D", geometry={"letterbox": 640})
        with pytest.raises(DatasetError, match="TRAIN_DATASET_IMG_SIZE=640"):
            ds.check_geometry(1280)


class TestBuildSplitTiles:
    """``build_split`` with the default tile geometry (real JPEGs; cv2 needed)."""

    def _service(self, tmp_path):
        cfg = SimpleNamespace(runs_dir=str(tmp_path / "runs"))
        svc = DatasetService(_DATASET_ID, str(tmp_path), config=cfg)
        svc.add_class("logo")
        return svc

    def _add(self, svc, width, height, boxes):
        cv2 = pytest.importorskip("cv2")
        np = pytest.importorskip("numpy")
        ok, buf = cv2.imencode(".jpg", np.full((height, width, 3), 90, dtype=np.uint8))
        assert ok
        entry = svc.add_image(buf.tobytes())
        svc.set_labels(entry.image_id, boxes)
        return entry.image_id

    def test_native_frames_become_tile_crops_and_square_ones_stay_whole(self, tmp_path):
        pytest.importorskip("cv2")
        svc = self._service(tmp_path)
        wide = [self._add(svc, 1280, 720, [Box(0, 0.5, 0.5, 0.1, 0.1)]) for _ in range(2)]
        square = self._add(svc, 640, 640, [Box(0, 0.5, 0.5, 0.1, 0.1)])

        result = svc.build_split("job-t", tile="auto")

        assert result.geometry == "tiles:auto"
        assert result.stats.tiles == 4 and result.stats.whole == 1
        assert result.train_count + result.valid_count == 5
        root = tmp_path / "runs" / "job-t" / "dataset"
        files = sorted(p.name for split in ("train", "valid")
                       for p in (root / split / "images").iterdir())
        assert files == sorted([f"{i}_t{k}.jpg" for i in wide for k in (0, 1)]
                               + [f"{square}.jpg"])
        assert (root / "train" / "images" / f"{square}.jpg").is_symlink() or \
            (root / "valid" / "images" / f"{square}.jpg").is_symlink()
        # A crop's label is renormalised to the 720 px tile: 128 px wide box → 128/720.
        crop_label = next(p for split in ("train", "valid")
                          for p in (root / split / "labels").iterdir()
                          if p.name == f"{wide[0]}_t0.txt")
        w = float(crop_label.read_text().split()[3])
        assert w == pytest.approx(128 / 720, abs=1e-3)

    def test_tile_off_keeps_the_symlink_layout(self, tmp_path):
        pytest.importorskip("cv2")
        svc = self._service(tmp_path)
        self._add(svc, 1280, 720, [Box(0, 0.5, 0.5, 0.1, 0.1)])
        self._add(svc, 1280, 720, [Box(0, 0.5, 0.5, 0.1, 0.1)])
        result = svc.build_split("job-w")
        assert result.geometry == "frames" and result.stats.tiles == 0
        root = tmp_path / "runs" / "job-w" / "dataset"
        assert all(p.is_symlink() for split in ("train", "valid")
                   for p in (root / split / "images").iterdir())

    def test_all_images_kept_whole_reports_frames(self, tmp_path):
        pytest.importorskip("cv2")
        svc = self._service(tmp_path)
        self._add(svc, 640, 640, [Box(0, 0.5, 0.5, 0.1, 0.1)])
        self._add(svc, 640, 640, [Box(0, 0.5, 0.5, 0.1, 0.1)])
        result = svc.build_split("job-l", tile="auto")
        assert result.geometry == "frames" and result.stats.whole == 2
