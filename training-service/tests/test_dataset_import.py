"""Unit tests for YOLO dataset ZIP import validation and normalization."""
import os
import zipfile

import cv2
import numpy as np
import pytest

from service.dataset_import import (
    DatasetImportError,
    _classes_from_yaml,
    _label_for,
    _parse_label_file,
    _validate_classes,
    import_dataset_zip,
)


def _jpeg():
    frame = np.full((80, 120, 3), 128, dtype=np.uint8)
    ok, buf = cv2.imencode(".jpg", frame)
    assert ok
    return buf.tobytes()


class TestValidateClasses:
    def test_valid(self):
        assert _validate_classes(["cap", "bottle"], "data.yaml") == ["cap", "bottle"]

    def test_empty_rejected(self):
        with pytest.raises(DatasetImportError):
            _validate_classes([], "data.yaml")

    def test_invalid_char_rejected(self):
        with pytest.raises(DatasetImportError):
            _validate_classes(["good", "bad/name"], "data.yaml")

    def test_too_long_rejected(self):
        with pytest.raises(DatasetImportError):
            _validate_classes(["x" * 65], "data.yaml")

    def test_duplicates_rejected(self):
        with pytest.raises(DatasetImportError):
            _validate_classes(["cap", "cap"], "data.yaml")


class TestClassesFromYaml:
    def test_list_form(self, tmp_path):
        p = tmp_path / "data.yaml"
        p.write_text("names: [cap, bottle]\n")
        assert _classes_from_yaml(str(p)) == ["cap", "bottle"]

    def test_dict_form_ordered_by_int_key(self, tmp_path):
        p = tmp_path / "data.yaml"
        p.write_text("names:\n  1: bottle\n  0: cap\n")
        assert _classes_from_yaml(str(p)) == ["cap", "bottle"]

    def test_missing_names_rejected(self, tmp_path):
        p = tmp_path / "data.yaml"
        p.write_text("train: images\n")
        with pytest.raises(DatasetImportError):
            _classes_from_yaml(str(p))


class TestLabelFor:
    def test_swaps_images_for_labels(self):
        img = os.path.join("root", "train", "images", "a.jpg")
        expected = os.path.join("root", "train", "labels", "a.txt")
        assert _label_for(img) == expected

    def test_sibling_txt_when_no_images_dir(self):
        img = os.path.join("root", "a.jpg")
        assert _label_for(img) == os.path.join("root", "a.txt")


class TestParseLabelFile:
    def test_detection_rows(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("0 0.5 0.5 0.2 0.2\n1 0.1 0.1 0.05 0.05\n")
        boxes = _parse_label_file(str(p), n_classes=2)
        assert boxes == [
            (0, 0.5, 0.5, 0.2, 0.2),
            (1, 0.1, 0.1, 0.05, 0.05),
        ]

    def test_polygon_row_collapses_to_bbox(self, tmp_path):
        p = tmp_path / "a.txt"
        # Square polygon from (0.2,0.2) to (0.6,0.6) -> center (0.4,0.4), w=h=0.4
        p.write_text("0 0.2 0.2 0.6 0.2 0.6 0.6 0.2 0.6\n")
        boxes = _parse_label_file(str(p), n_classes=1)
        assert boxes[0][0] == 0
        assert boxes[0][1] == pytest.approx(0.4)
        assert boxes[0][2] == pytest.approx(0.4)
        assert boxes[0][3] == pytest.approx(0.4)
        assert boxes[0][4] == pytest.approx(0.4)

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("\n0 0.5 0.5 0.2 0.2\n\n")
        assert len(_parse_label_file(str(p), n_classes=1)) == 1

    def test_non_numeric_rejected(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("0 a b c d\n")
        with pytest.raises(DatasetImportError):
            _parse_label_file(str(p), n_classes=1)

    def test_class_out_of_range_rejected(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("5 0.5 0.5 0.2 0.2\n")
        with pytest.raises(DatasetImportError):
            _parse_label_file(str(p), n_classes=2)

    def test_coords_out_of_range_rejected(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("0 1.5 0.5 0.2 0.2\n")
        with pytest.raises(DatasetImportError):
            _parse_label_file(str(p), n_classes=1)

    def test_wrong_value_count_rejected(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("0 0.5 0.5\n")
        with pytest.raises(DatasetImportError):
            _parse_label_file(str(p), n_classes=1)


class TestImportDatasetZip:
    def _make_zip(self, tmp_path, with_label=True):
        zip_path = tmp_path / "ds.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("data.yaml", "names: [cap, bottle]\n")
            z.writestr("images/img1.jpg", _jpeg())
            if with_label:
                z.writestr("labels/img1.txt", "0 0.5 0.5 0.2 0.2\n")
        return str(zip_path)

    def test_valid_import(self, tmp_path):
        zip_path = self._make_zip(tmp_path)
        dest = tmp_path / "out"
        classes, count = import_dataset_zip(zip_path, str(dest))
        assert classes == ["cap", "bottle"]
        assert count == 1
        assert (dest / "classes.json").exists()
        assert len(list((dest / "images").glob("*.jpg"))) == 1
        assert len(list((dest / "labels").glob("*.txt"))) == 1

    def test_unlabeled_image_still_imported(self, tmp_path):
        zip_path = self._make_zip(tmp_path, with_label=False)
        dest = tmp_path / "out"
        classes, count = import_dataset_zip(zip_path, str(dest))
        assert count == 1
        assert len(list((dest / "labels").glob("*.txt"))) == 0

    def test_bad_zip_rejected(self, tmp_path):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        with pytest.raises(DatasetImportError):
            import_dataset_zip(str(bad), str(tmp_path / "out"))

    def test_missing_classes_rejected(self, tmp_path):
        zip_path = tmp_path / "noclasses.zip"
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("images/img1.jpg", _jpeg())
        with pytest.raises(DatasetImportError):
            import_dataset_zip(str(zip_path), str(tmp_path / "out"))
