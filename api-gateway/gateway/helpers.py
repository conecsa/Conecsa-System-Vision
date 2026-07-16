"""Shared response, content-negotiation, event and gRPC-error helpers for the
gateway controllers (mirror api_server.py)."""
import json
import logging
import os
import socket
import threading
import time
from typing import FrozenSet, TypedDict

import grpc
from flask import Response, request

from .events import event_service

logger = logging.getLogger(__name__)

# Device software version, surfaced on /api/v1/status and /api/v1/health so the
# conecsa-hub-vision hub can display it. Set DEVICE_VERSION in docker-compose.
DEVICE_VERSION = os.environ.get("DEVICE_VERSION", "unknown")

# The compose service running the nginx mTLS terminator — the only peer allowed
# to assert X-Conecsa-Client-Verify. Every other container on the docker
# network can reach the gateway directly and could spoof the header.
TRUSTED_PROXY_HOST = os.environ.get("TRUSTED_PROXY_HOST", "system-vision")

_PROXY_CACHE_TTL_SEC = 30.0


class _ProxyCache(TypedDict):
    ips: FrozenSet[str]
    at: float  # time.monotonic() of the last resolution


_proxy_cache: _ProxyCache = {"ips": frozenset(), "at": float("-inf")}
_proxy_lock = threading.Lock()


def _resolve_proxy_ips() -> FrozenSet[str]:
    """Addresses TRUSTED_PROXY_HOST currently resolves to (empty if none)."""
    try:
        # str() narrows the sockaddr's loosely-typed first element; for the
        # AF_INET/AF_INET6 families docker DNS returns it is already a string.
        return frozenset(
            str(info[4][0])
            for info in socket.getaddrinfo(TRUSTED_PROXY_HOST, None))
    except OSError:
        return frozenset()


def _is_trusted_proxy(addr: str) -> bool:
    """Whether *addr* is the nginx terminator's container.

    Docker-DNS lookup with a short cache; a cache miss re-resolves immediately
    so an nginx restart (new container IP) is honored on the next request.
    """
    with _proxy_lock:
        if addr in _proxy_cache["ips"] and \
                time.monotonic() - _proxy_cache["at"] < _PROXY_CACHE_TTL_SEC:
            return True
        _proxy_cache["ips"] = _resolve_proxy_ips()
        _proxy_cache["at"] = time.monotonic()
        return addr in _proxy_cache["ips"]


def _hub_verified() -> bool:
    """True only when the request is a hub call relayed by the mTLS terminator.

    The X-Conecsa-Client-Verify header alone proves nothing — any container on
    the compose network can call the gateway directly and set it — so it only
    counts when the TCP peer is the terminator itself. nginx stamps the header
    from $ssl_client_verify on :443 (where only the paired hub can complete the
    handshake) and clears it on the plaintext listener.
    """
    if request.headers.get("X-Conecsa-Client-Verify", "") != "SUCCESS":
        return False
    if _is_trusted_proxy(request.remote_addr or ""):
        return True
    logger.warning("X-Conecsa-Client-Verify=SUCCESS from untrusted peer %s — "
                   "ignoring", request.remote_addr)
    return False


def _json(data, status=200) -> Response:
    """Build a JSON Response with the given body and status."""
    return Response(json.dumps(data), status=status, mimetype="application/json")


def _json_error(message, status=400) -> Response:
    """Build a JSON ``{"error": message}`` Response (default 400)."""
    return _json({"error": message}, status)


def _json_success(message="Success", **kwargs) -> Response:
    """Build a JSON success Response, merging any extra ``kwargs``."""
    data = {"status": "success", "message": message}
    data.update(kwargs)
    return _json(data)


def _accepts_protobuf() -> bool:
    """True if the client's Accept header opts into protobuf responses."""
    return "application/x-protobuf" in request.headers.get("Accept", "")


def _protobuf(message, status=200) -> Response:
    """Serialize a protobuf *message* into an ``application/x-protobuf`` Response."""
    return Response(message.SerializeToString(), status=status,
                    mimetype="application/x-protobuf")


def _should_use_json(check_content_type=False) -> bool:
    """Whether to treat the request/response as JSON (Accept or Content-Type)."""
    if check_content_type:
        return "application/json" in request.headers.get("Content-Type", "")
    accept = request.headers.get("Accept", "")
    return "application/json" in accept or "text/html" in accept


def _event_source(default="api"):
    """The client's ``X-Conecsa-Source`` header (which client triggered this)."""
    return request.headers.get("X-Conecsa-Source", default)


def _publish_event(event_type, keys, data=None, source=None):
    """Publish an invalidation event onto the unified SSE stream."""
    event_service.publish(event_type, keys=keys, source=source or _event_source(),
                          data=data or {})


def _response_json(resp: Response) -> dict:
    """Parse a Response body as JSON, or ``{}`` if it isn't JSON."""
    try:
        return json.loads(resp.get_data(as_text=True))
    except Exception:  # noqa: BLE001
        return {}


def _publish_if_success(resp: Response, event_type, keys, data=None, source=None) -> Response:
    """Publish an event only when *resp* is a non-error, non-failure response."""
    body = data if isinstance(data, dict) else _response_json(resp)
    if resp.status_code < 400 and body.get("success", True) is not False:
        _publish_event(event_type, keys, data=data, source=source)
    return resp


def _grpc_error(exc: grpc.RpcError) -> Response:
    """Map a gRPC error to a JSON Response (503 for unavailable/timeout, else 500)."""
    detail = exc.details() if hasattr(exc, "details") else str(exc)
    code = exc.code() if hasattr(exc, "code") else None
    status = 503 if code in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED) else 500
    logger.error("inference RPC failed: %s", detail)
    return _json_error(f"Inference service error: {detail}", status)
