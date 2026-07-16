"""Unit tests for the best-effort SAM unload in POST /api/v1/start.

Training's SAM assistant must never stay GPU-pinned once detection runs, but
an unreachable training-service must not block the start either.
"""
from types import SimpleNamespace

import grpc
import pytest
from flask import Flask

from gateway.controllers import detection

import inference_pb2 as inf_pb


class FakeRpcError(grpc.RpcError):
    pass


@pytest.fixture
def app():
    return Flask(__name__)


def _wire(monkeypatch, sam_loaded=True, sam_status_raises=False,
          unload_raises=False):
    """Stub every gRPC surface start_detection touches; returns the call log."""
    calls = []

    def get_status(_):
        calls.append("get_status")
        return inf_pb.StatusResponse(is_running=False, camera_connected=True)

    def get_sam_status(_):
        calls.append("get_sam_status")
        if sam_status_raises:
            raise FakeRpcError()
        return SimpleNamespace(loaded=sam_loaded)

    def unload_sam(_):
        calls.append("unload_sam")
        if unload_raises:
            raise FakeRpcError()

    def start(_):
        calls.append("start")
        return SimpleNamespace(success=True, message="Detection started")

    monkeypatch.setattr(
        detection, "clients",
        SimpleNamespace(
            detection=SimpleNamespace(GetStatus=get_status, Start=start),
            training=SimpleNamespace(GetSamStatus=get_sam_status,
                                     UnloadSam=unload_sam)))
    # Keep the SSE side out of the unit: pass the response through untouched.
    monkeypatch.setattr(detection, "_publish_if_success",
                        lambda resp, *a, **kw: resp)
    return calls


def _post_start(app):
    with app.test_request_context("/api/v1/start", method="POST"):
        return detection.start_detection()


def test_loaded_sam_is_unloaded_before_start(app, monkeypatch):
    calls = _wire(monkeypatch, sam_loaded=True)
    resp = _post_start(app)
    assert resp.status_code == 200
    assert calls == ["get_status", "get_sam_status", "unload_sam", "start"]


def test_unloaded_sam_is_left_alone(app, monkeypatch):
    # The status probe avoids a spurious sam_changed event from the
    # unconditional publish in SamService.unload().
    calls = _wire(monkeypatch, sam_loaded=False)
    resp = _post_start(app)
    assert resp.status_code == 200
    assert "unload_sam" not in calls
    assert calls[-1] == "start"


def test_unreachable_training_service_does_not_block_start(app, monkeypatch):
    calls = _wire(monkeypatch, sam_status_raises=True)
    resp = _post_start(app)
    assert resp.status_code == 200
    assert "unload_sam" not in calls
    assert calls[-1] == "start"


def test_failing_unload_does_not_block_start(app, monkeypatch):
    calls = _wire(monkeypatch, sam_loaded=True, unload_raises=True)
    resp = _post_start(app)
    assert resp.status_code == 200
    assert calls[-1] == "start"
