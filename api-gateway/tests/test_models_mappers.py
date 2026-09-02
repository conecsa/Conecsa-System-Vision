"""Unit tests for the model/conversion gRPC message -> JSON mapper."""
from types import SimpleNamespace

import pytest
from gateway.controllers.models import _conversion_dict, _train_geometry_from_form


def _job(**kw):
    base = dict(
        job_id="j1",
        original_filename="best.pt",
        status="converting_to_engine",
        progress=45,
        message="ONNX export complete. Building TensorRT engine…",
        error="",
        engine_filename="",
        started_at=1234.5,
        elapsed_secs=87.25,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestConversionDict:
    def test_relays_every_field(self):
        d = _conversion_dict(_job())
        assert d == {
            "job_id": "j1",
            "original_filename": "best.pt",
            "status": "converting_to_engine",
            "progress": 45,
            "message": "ONNX export complete. Building TensorRT engine…",
            "error": "",
            "engine_filename": "",
            "started_at": 1234.5,
            "elapsed_secs": 87.25,
        }

    def test_elapsed_is_independent_of_started_at(self):
        # The UI must never derive the age from `started_at`: that is the
        # device's wall clock, which the hub steps and which the browser does
        # not share. A 1970 `started_at` must not disturb `elapsed_secs`.
        d = _conversion_dict(_job(started_at=0.0))
        assert d["elapsed_secs"] == 87.25


class TestTrainGeometryForm:
    @pytest.mark.parametrize("raw,expected", [
        ("frames", "frames"), ("tiles:auto", "tiles:auto"), (" Tiles:720 ", "tiles:720"),
        (None, ""), ("", ""), ("tiles:0", ""), ("tiles:07", ""), ("grid", ""),
        ("frames; drop", ""),
    ])
    def test_only_well_formed_values_pass(self, raw, expected):
        assert _train_geometry_from_form(raw) == expected
