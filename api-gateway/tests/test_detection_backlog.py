"""Unit tests for the detection-backlog relay endpoints (offline buffer drain)."""
import json

import grpc
import pytest
from flask import Flask

from gateway import grpc_clients, helpers
from gateway.controllers import api_bp

import inference_pb2 as inf_pb


class FakeRpcError(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNAVAILABLE

    def details(self):
        return "inference down"


class FakeDetectionStub:
    """Records the requests the endpoints build and plays back canned replies."""

    def __init__(self):
        self.backlog_requests = []
        self.ack_requests = []
        self.snapshot_requests = []
        self.backlog_json = json.dumps(
            {"records": [{"id": 1}], "device_now": 123.0, "pending": 1})
        self.raise_error = False

    def Snapshot(self, request):
        if self.raise_error:
            raise FakeRpcError()
        self.snapshot_requests.append(request)
        return inf_pb.SnapshotResponse(json=json.dumps({"total": 0}))

    def ListBacklog(self, request):
        if self.raise_error:
            raise FakeRpcError()
        self.backlog_requests.append(request)
        return inf_pb.BacklogResponse(json=self.backlog_json)

    def AckBacklog(self, request):
        if self.raise_error:
            raise FakeRpcError()
        self.ack_requests.append(request)
        n = len(request.ids)
        return inf_pb.Result(success=True, message=f"{n} records acknowledged")


@pytest.fixture
def stub(monkeypatch):
    stub = FakeDetectionStub()
    monkeypatch.setattr(grpc_clients.clients, "detection", stub)
    return stub


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    return app.test_client()


TERMINATOR_IP = "10.66.0.9"


@pytest.fixture
def trusted_proxy(monkeypatch):
    """Pin the trusted-proxy DNS resolution to TERMINATOR_IP, cold cache."""
    monkeypatch.setattr(helpers, "_resolve_proxy_ips",
                        lambda: frozenset({TERMINATOR_IP}))
    monkeypatch.setattr(helpers, "_proxy_cache",
                        {"ips": frozenset(), "at": float("-inf")})


class TestSnapshotHubHeartbeat:
    """Only pulls stamped AND relayed by the mTLS terminator count as hub
    contact — the header alone can be forged by any docker-network client."""

    def test_mtls_verified_pull_is_marked_as_hub(self, client, stub,
                                                 trusted_proxy):
        client.get("/api/v1/detections/snapshot",
                   headers={"X-Conecsa-Client-Verify": "SUCCESS"},
                   environ_base={"REMOTE_ADDR": TERMINATOR_IP})
        assert stub.snapshot_requests[-1].hub_pull is True

    def test_local_pull_is_not_marked_as_hub(self, client, stub):
        # A Flow node (or any docker-network client) hits the gateway directly,
        # without the terminator's header: it must not feed the heartbeat.
        client.get("/api/v1/detections/snapshot")
        assert stub.snapshot_requests[-1].hub_pull is False

    def test_unverified_header_is_not_marked_as_hub(self, client, stub):
        client.get("/api/v1/detections/snapshot",
                   headers={"X-Conecsa-Client-Verify": "NONE"})
        assert stub.snapshot_requests[-1].hub_pull is False

    def test_spoofed_header_from_untrusted_peer_is_not_marked_as_hub(
            self, client, stub, trusted_proxy):
        # A container forging the header while calling the gateway directly:
        # the TCP peer is not the terminator, so it must not count.
        client.get("/api/v1/detections/snapshot",
                   headers={"X-Conecsa-Client-Verify": "SUCCESS"},
                   environ_base={"REMOTE_ADDR": "172.20.0.5"})
        assert stub.snapshot_requests[-1].hub_pull is False

    def test_a_terminator_restart_is_picked_up_on_the_next_pull(
            self, client, stub, monkeypatch):
        # Fresh cache holds the old container IP; a pull from the new IP must
        # force a re-resolve instead of waiting out the TTL.
        import time
        monkeypatch.setattr(helpers, "_resolve_proxy_ips",
                            lambda: frozenset({TERMINATOR_IP}))
        monkeypatch.setattr(helpers, "_proxy_cache",
                            {"ips": frozenset({"10.66.0.2"}),
                             "at": time.monotonic()})
        client.get("/api/v1/detections/snapshot",
                   headers={"X-Conecsa-Client-Verify": "SUCCESS"},
                   environ_base={"REMOTE_ADDR": TERMINATOR_IP})
        assert stub.snapshot_requests[-1].hub_pull is True


class TestListBacklog:
    def test_relays_the_json_verbatim(self, client, stub):
        resp = client.get("/api/v1/detections/backlog")
        assert resp.status_code == 200
        assert resp.mimetype == "application/json"
        assert resp.get_data(as_text=True) == stub.backlog_json

    def test_propagates_the_limit(self, client, stub):
        client.get("/api/v1/detections/backlog?limit=7")
        assert stub.backlog_requests[-1].limit == 7

    def test_omitted_limit_lets_the_service_default(self, client, stub):
        client.get("/api/v1/detections/backlog")
        assert stub.backlog_requests[-1].limit == 0

    def test_negative_limit_is_rejected(self, client, stub):
        resp = client.get("/api/v1/detections/backlog?limit=-1")
        assert resp.status_code == 400
        assert stub.backlog_requests == []

    def test_oversized_limit_is_clamped(self, client, stub):
        client.get("/api/v1/detections/backlog?limit=5000")
        assert stub.backlog_requests[-1].limit == 100

    def test_grpc_failure_maps_to_gateway_error(self, client, stub):
        stub.raise_error = True
        resp = client.get("/api/v1/detections/backlog")
        assert resp.status_code == 503
        assert "error" in resp.get_json()


class TestAckBacklog:
    def test_relays_ids_and_reports_the_result(self, client, stub):
        resp = client.post("/api/v1/detections/backlog/ack",
                           json={"ids": [1, 2, 3]})
        assert resp.status_code == 200
        assert resp.get_json() == {
            "success": True, "message": "3 records acknowledged"}
        assert list(stub.ack_requests[-1].ids) == [1, 2, 3]

    @pytest.mark.parametrize("body", [
        None,
        {},
        {"ids": "1,2"},
        {"ids": [1, "two"]},
        {"other": []},
    ])
    def test_rejects_malformed_bodies(self, client, stub, body):
        resp = client.post("/api/v1/detections/backlog/ack", json=body)
        assert resp.status_code == 400
        assert stub.ack_requests == []

    def test_empty_id_list_is_a_valid_noop(self, client, stub):
        resp = client.post("/api/v1/detections/backlog/ack", json={"ids": []})
        assert resp.status_code == 200
        assert list(stub.ack_requests[-1].ids) == []

    def test_grpc_failure_maps_to_gateway_error(self, client, stub):
        stub.raise_error = True
        resp = client.post("/api/v1/detections/backlog/ack", json={"ids": [1]})
        assert resp.status_code == 503
