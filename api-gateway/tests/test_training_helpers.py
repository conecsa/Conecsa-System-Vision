"""Unit tests for the training route helpers (responses + gRPC error mapping)."""
import json
from types import SimpleNamespace

import grpc
import pytest

from gateway.training.helpers import _grpc_error, _json, _json_error, _result


class FakeRpcError(grpc.RpcError):
    def __init__(self, code, details="boom"):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


class TestGrpcError:
    @pytest.mark.parametrize(
        "code, status",
        [
            (grpc.StatusCode.NOT_FOUND, 404),
            (grpc.StatusCode.FAILED_PRECONDITION, 409),
            (grpc.StatusCode.INVALID_ARGUMENT, 400),
            (grpc.StatusCode.UNAVAILABLE, 503),
            (grpc.StatusCode.DEADLINE_EXCEEDED, 503),
            (grpc.StatusCode.INTERNAL, 500),
        ],
    )
    def test_status_mapping(self, code, status):
        resp = _grpc_error(FakeRpcError(code, details="no dataset"))
        assert resp.status_code == status
        assert "no dataset" in json.loads(resp.get_data(as_text=True))["error"]

    def test_client_errors_keep_the_bare_detail(self):
        resp = _grpc_error(FakeRpcError(grpc.StatusCode.NOT_FOUND, details="gone"))
        assert json.loads(resp.get_data(as_text=True)) == {"error": "gone"}

    def test_server_errors_are_prefixed(self):
        resp = _grpc_error(FakeRpcError(grpc.StatusCode.INTERNAL, details="oops"))
        body = json.loads(resp.get_data(as_text=True))
        assert body["error"] == "Training service error: oops"


class TestResult:
    def test_success_maps_to_json_success(self):
        resp = _result(SimpleNamespace(success=True, message="started"), ok_status=201)
        assert resp.status_code == 201
        assert json.loads(resp.get_data(as_text=True)) == {
            "status": "success",
            "message": "started",
        }

    def test_failure_maps_to_400_with_message(self):
        resp = _result(SimpleNamespace(success=False, message="too few images"))
        assert resp.status_code == 400
        assert json.loads(resp.get_data(as_text=True)) == {"error": "too few images"}

    def test_failure_without_message_gets_a_default(self):
        resp = _result(SimpleNamespace(success=False, message=""))
        body = json.loads(resp.get_data(as_text=True))
        assert body["error"] == "Operation failed (no detail reported)"


class TestJsonHelpers:
    def test_json_and_error_shapes(self):
        assert _json({"a": 1}).status_code == 200
        resp = _json_error("bad", 422)
        assert resp.status_code == 422
        assert json.loads(resp.get_data(as_text=True)) == {"error": "bad"}
