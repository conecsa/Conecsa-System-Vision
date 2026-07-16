"""Unit tests for the shared gateway response/content-negotiation helpers."""
import json

import grpc
import pytest
from flask import Flask

from gateway import helpers
from gateway.helpers import (
    _accepts_protobuf,
    _event_source,
    _grpc_error,
    _json,
    _json_error,
    _json_success,
    _publish_if_success,
    _response_json,
    _should_use_json,
)


class FakeRpcError(grpc.RpcError):
    def __init__(self, code, details="boom"):
        self._code = code
        self._details = details

    def code(self):
        return self._code

    def details(self):
        return self._details


@pytest.fixture
def app():
    return Flask(__name__)


class TestJsonResponses:
    def test_json_body_status_and_mimetype(self):
        resp = _json({"a": 1}, status=201)
        assert resp.status_code == 201
        assert resp.mimetype == "application/json"
        assert json.loads(resp.get_data(as_text=True)) == {"a": 1}

    def test_json_error_shape(self):
        resp = _json_error("nope")
        assert resp.status_code == 400
        assert json.loads(resp.get_data(as_text=True)) == {"error": "nope"}

    def test_json_success_merges_extra_fields(self):
        resp = _json_success("done", job_id="j1")
        assert resp.status_code == 200
        assert json.loads(resp.get_data(as_text=True)) == {
            "status": "success",
            "message": "done",
            "job_id": "j1",
        }


class TestContentNegotiation:
    def test_accepts_protobuf_only_with_explicit_accept(self, app):
        with app.test_request_context(headers={"Accept": "application/x-protobuf"}):
            assert _accepts_protobuf() is True
        with app.test_request_context(headers={"Accept": "application/json"}):
            assert _accepts_protobuf() is False
        with app.test_request_context():
            assert _accepts_protobuf() is False

    def test_should_use_json_reads_accept_header(self, app):
        with app.test_request_context(headers={"Accept": "application/json"}):
            assert _should_use_json() is True
        with app.test_request_context(headers={"Accept": "text/html"}):
            assert _should_use_json() is True
        with app.test_request_context(headers={"Accept": "application/x-protobuf"}):
            assert _should_use_json() is False

    def test_should_use_json_can_check_content_type_instead(self, app):
        with app.test_request_context(
            headers={"Content-Type": "application/json", "Accept": "text/plain"}
        ):
            assert _should_use_json(check_content_type=True) is True
        with app.test_request_context(headers={"Accept": "application/json"}):
            assert _should_use_json(check_content_type=True) is False

    def test_event_source_header_with_default(self, app):
        with app.test_request_context(headers={"X-Conecsa-Source": "flow"}):
            assert _event_source() == "flow"
        with app.test_request_context():
            assert _event_source() == "api"
            assert _event_source(default="ui") == "ui"


class TestGrpcError:
    @pytest.mark.parametrize(
        "code, status",
        [
            (grpc.StatusCode.UNAVAILABLE, 503),
            (grpc.StatusCode.DEADLINE_EXCEEDED, 503),
            (grpc.StatusCode.INTERNAL, 500),
            (grpc.StatusCode.NOT_FOUND, 500),
        ],
    )
    def test_status_mapping(self, code, status):
        resp = _grpc_error(FakeRpcError(code, details="down"))
        assert resp.status_code == status
        assert "down" in json.loads(resp.get_data(as_text=True))["error"]

    def test_error_without_code_or_details_is_500(self):
        resp = _grpc_error(grpc.RpcError("bare"))
        assert resp.status_code == 500


class TestResponseJson:
    def test_parses_json_body(self):
        assert _response_json(_json({"ok": True})) == {"ok": True}

    def test_non_json_body_is_empty_dict(self):
        from flask import Response

        assert _response_json(Response("<html>", mimetype="text/html")) == {}


class TestPublishIfSuccess:
    @pytest.fixture
    def published(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            helpers, "_publish_event",
            lambda event_type, keys, data=None, source=None: calls.append(event_type),
        )
        return calls

    def test_publishes_on_success_response(self, published):
        _publish_if_success(_json({"ok": True}), "model_changed", ["models"])
        assert published == ["model_changed"]

    def test_skips_on_http_error(self, published):
        _publish_if_success(_json_error("bad"), "model_changed", ["models"])
        assert published == []

    def test_skips_when_body_reports_failure(self, published):
        _publish_if_success(_json({"success": False}), "model_changed", ["models"])
        assert published == []
