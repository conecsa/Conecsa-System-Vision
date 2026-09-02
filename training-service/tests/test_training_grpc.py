"""Unit tests for the TrainingControl servicer's GetImage dimension reporting.

The servicer is built over a fake application whose dataset registry hands
back an in-memory dataset, so no gRPC server, capture or training service is
involved.
"""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
import training_pb2 as pb
from service.training_grpc import TrainingControlServicer, _geometry_dimensions


class FakeDataset:
    def __init__(self, blob: bytes, geometry: dict):
        self._blob = blob
        self._geometry = geometry

    def get_image_bytes(self, image_id):
        return self._blob

    def geometry(self):
        return dict(self._geometry)


class FakeContext:
    def __init__(self):
        self.code = None
        self.details = None

    def set_code(self, code):
        self.code = code

    def set_details(self, details):
        self.details = details


def _servicer(dataset):
    registry = SimpleNamespace(get=lambda dataset_id: dataset)
    return TrainingControlServicer(SimpleNamespace(dataset_registry=registry))


def _jpeg(w: int, h: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", np.zeros((h, w, 3), dtype=np.uint8))
    assert ok
    return buf.tobytes()


class TestGeometryDimensions:
    def test_letterbox_square(self):
        assert _geometry_dimensions({"letterbox": 640}) == (640, 640)
        assert _geometry_dimensions({"letterbox": 1280}) == (1280, 1280)

    def test_native_is_unknown(self):
        assert _geometry_dimensions({"native": True}) == (0, 0)
        assert _geometry_dimensions({}) == (0, 0)


class TestGetImage:
    @pytest.mark.parametrize("geometry", [{"letterbox": 640}, {"native": True}])
    def test_readable_blob_reports_its_own_size(self, geometry):
        blob = _jpeg(320, 200)
        reply = _servicer(FakeDataset(blob, geometry)).GetImage(
            pb.ImageId(dataset_id="d", image_id="i"), FakeContext())
        assert reply.jpeg == blob
        assert (reply.width, reply.height) == (320, 200)

    def test_unreadable_blob_in_letterbox_dataset_reports_the_square(self):
        ctx = FakeContext()
        reply = _servicer(FakeDataset(b"not a jpeg", {"letterbox": 1280})).GetImage(
            pb.ImageId(dataset_id="d", image_id="i"), ctx)
        assert ctx.code is None
        assert reply.jpeg == b"not a jpeg"
        assert (reply.width, reply.height) == (1280, 1280)

    def test_unreadable_blob_in_native_dataset_reports_unknown(self):
        ctx = FakeContext()
        reply = _servicer(FakeDataset(b"not a jpeg", {"native": True})).GetImage(
            pb.ImageId(dataset_id="d", image_id="i"), ctx)
        assert ctx.code is None
        assert reply.jpeg == b"not a jpeg"
        assert (reply.width, reply.height) == (0, 0)
