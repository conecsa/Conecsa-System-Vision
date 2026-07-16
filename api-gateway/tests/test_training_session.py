"""Unit tests for the shared exit-training-mode helper (session._do_exit)."""
from types import SimpleNamespace

import grpc
import pytest

from gateway.training import session


class FakeRpcError(grpc.RpcError):
    pass


@pytest.fixture
def events(monkeypatch):
    """Capture SSE publishes; returns the (event, data) call list."""
    calls = []
    monkeypatch.setattr(
        session, "event_service",
        SimpleNamespace(publish=lambda event, keys=None, data=None:
                        calls.append((event, data))))
    return calls


def _wire(monkeypatch, resume_result=None, resume_raises=False,
          unload_raises=False):
    """Stub the two gRPC surfaces _do_exit touches; returns the call log."""
    calls = []

    def unload_sam(_):
        calls.append("unload_sam")
        if unload_raises:
            raise FakeRpcError()

    def resume(_):
        calls.append("resume")
        if resume_raises:
            raise FakeRpcError()
        return resume_result

    monkeypatch.setattr(
        session, "clients",
        SimpleNamespace(training=SimpleNamespace(UnloadSam=unload_sam),
                        management=SimpleNamespace(ResumeRuntime=resume)))
    return calls


def test_no_resume_leaves_the_runtime_released(monkeypatch, events):
    calls = _wire(monkeypatch)
    ok, message = session._do_exit(resume_detection=False)
    assert ok
    assert "conversion" in message
    assert "resume" not in calls, "the runtime must stay released"
    assert events == [("detection_state_changed", {"is_running": False})]


def test_resume_success(monkeypatch, events):
    calls = _wire(monkeypatch,
                  resume_result=SimpleNamespace(success=True, message="resumed"))
    ok, message = session._do_exit(resume_detection=True)
    assert (ok, message) == (True, "resumed")
    assert calls == ["unload_sam", "resume"]
    assert events == [("detection_state_changed", {"is_running": True})]


def test_resume_refusal_reports_failure(monkeypatch, events):
    _wire(monkeypatch,
          resume_result=SimpleNamespace(success=False, message="busy"))
    ok, message = session._do_exit(resume_detection=True)
    assert (ok, message) == (False, "busy")
    assert events == [], "no state-change event on a failed resume"


def test_resume_rpc_error_propagates(monkeypatch, events):
    _wire(monkeypatch, resume_raises=True)
    with pytest.raises(grpc.RpcError):
        session._do_exit(resume_detection=True)
    assert events == []


def test_unload_sam_failure_is_best_effort(monkeypatch, events):
    calls = _wire(monkeypatch, unload_raises=True,
                  resume_result=SimpleNamespace(success=True, message="ok"))
    ok, _ = session._do_exit(resume_detection=True)
    assert ok
    assert calls == ["unload_sam", "resume"], "resume must still run"


def test_heartbeat_returns_json_ok():
    # The whole effect is the blueprint's before_request hook (tracker.touch,
    # covered by test_orphan.py); the route itself must only answer 200 with a
    # JSON body — the frontend transport parses every response as JSON.
    from flask import Flask

    with Flask(__name__).test_request_context("/api/v1/training/heartbeat",
                                              method="POST"):
        resp = session.training_heartbeat()
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}
