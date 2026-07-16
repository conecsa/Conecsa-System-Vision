"""Unit tests for the training gRPC message -> JSON mappers."""
from types import SimpleNamespace

import pytest

from gateway.training import _job_dict, _meta_dict, _parse_named_boxes


def _job(**kw):
    base = dict(
        job_id="j1",
        status="running",
        progress=42,
        epoch=5,
        total_epochs=50,
        message="training",
        error="",
        model_name="best.pt",
        conversion_job_id="",
        metrics_json='{"mAP": 0.8}',
        started_at=1234.5,
        dataset_id="d1",
        federated=False,
        result_weights_id="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestJobDict:
    def test_full_job(self):
        d = _job_dict(_job())
        assert d["job_id"] == "j1"
        assert d["progress"] == 42
        assert d["metrics"] == {"mAP": 0.8}
        assert d["dataset_id"] == "d1"

    def test_empty_status_defaults_to_idle(self):
        assert _job_dict(_job(status=""))["status"] == "idle"

    def test_empty_metrics_json_is_empty_dict(self):
        assert _job_dict(_job(metrics_json=""))["metrics"] == {}

    def test_invalid_metrics_json_is_empty_dict(self):
        assert _job_dict(_job(metrics_json="{not json"))["metrics"] == {}

    def test_federated_fields_are_mapped(self):
        d = _job_dict(_job(federated=True, result_weights_id="abc123"))
        assert d["federated"] is True
        assert d["result_weights_id"] == "abc123"


class TestMetaDict:
    def test_full_meta(self):
        m = SimpleNamespace(
            dataset_id="d1",
            name="My Dataset",
            created_at=100.0,
            cover_image_id="img1",
            image_count=10,
            labeled_count=7,
            class_count=3,
        )
        assert _meta_dict(m) == {
            "dataset_id": "d1",
            "name": "My Dataset",
            "created_at": 100.0,
            "cover_image_id": "img1",
            "image_count": 10,
            "labeled_count": 7,
            "class_count": 3,
        }


class TestParseNamedBoxes:
    def test_valid_list(self):
        boxes = _parse_named_boxes(
            '[{"class_name": "cap", "x1": 0.1, "y1": 0.2, "x2": 0.5, "y2": 0.6}]'
        )
        assert len(boxes) == 1
        assert boxes[0].class_name == "cap"
        assert boxes[0].x1 == pytest.approx(0.1)
        assert boxes[0].y2 == pytest.approx(0.6)

    def test_empty_defaults_to_no_boxes(self):
        assert _parse_named_boxes("") == []
        assert _parse_named_boxes("[]") == []

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError):
            _parse_named_boxes("{not json")

    def test_non_list_raises(self):
        with pytest.raises(ValueError):
            _parse_named_boxes('{"class_name": "cap"}')

    def test_non_dict_entry_raises(self):
        with pytest.raises(ValueError):
            _parse_named_boxes('["cap"]')

    def test_non_numeric_coord_raises(self):
        with pytest.raises(ValueError):
            _parse_named_boxes('[{"class_name": "cap", "x1": "left"}]')
