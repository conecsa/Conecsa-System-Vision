"""Network controller: wired configuration and Wi-Fi scan/connect/forget via
the os hardware agent."""
import logging

import grpc
from flask import Response, request

from .. import hardware
from ..helpers import _json, _publish_if_success
from . import api_bp

logger = logging.getLogger(__name__)


def _network_agent_error(exc: grpc.RpcError) -> Response:
    """Map a hardware-agent gRPC error to a 503 JSON Response."""
    detail = exc.details() if hasattr(exc, "details") else str(exc)
    logger.error("hardware agent RPC failed: %s", detail)
    return _json({"error": f"Hardware agent unavailable: {detail}"}, 503)


@api_bp.route('/api/v1/network/config', methods=['GET'])
def get_network_config():
    """GET /api/v1/network/config — gateway relay."""
    try:
        return _json(hardware.get_network_config())
    except grpc.RpcError as exc:
        return _network_agent_error(exc)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": str(exc)}, 500)


@api_bp.route('/api/v1/network/config', methods=['POST'])
def set_network_config():
    """POST /api/v1/network/config — gateway relay."""
    body = request.get_json(silent=True) or {}
    method = body.get("method")
    if not method:
        return _json({"error": "'method' field is required"}, 400)
    try:
        result = hardware.set_network_config(
            interface=body.get("interface", "wired"), method=method,
            address=body.get("address"), prefix=body.get("prefix"),
            gateway=body.get("gateway"), dns=body.get("dns"))
    except grpc.RpcError as exc:
        return _network_agent_error(exc)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": str(exc)}, 500)
    return _publish_if_success(_json(result), "network_config_changed", ["network"], data=result)


@api_bp.route('/api/v1/network/wifi/scan', methods=['GET'])
def scan_wifi():
    """GET /api/v1/network/wifi/scan — gateway relay."""
    try:
        return _json(hardware.scan_wifi())
    except grpc.RpcError as exc:
        return _network_agent_error(exc)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": str(exc)}, 500)


@api_bp.route('/api/v1/network/wifi/connect', methods=['POST'])
def connect_wifi():
    """POST /api/v1/network/wifi/connect — gateway relay."""
    body = request.get_json(silent=True) or {}
    ssid = body.get("ssid")
    if not ssid:
        return _json({"error": "'ssid' field is required"}, 400)
    try:
        result = hardware.connect_wifi(ssid, body.get("password", ""))
    except grpc.RpcError as exc:
        return _network_agent_error(exc)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": str(exc)}, 500)
    return _publish_if_success(_json(result), "network_config_changed", ["network"], data=result)


@api_bp.route('/api/v1/network/wifi/forget', methods=['POST'])
def forget_wifi():
    """POST /api/v1/network/wifi/forget — gateway relay."""
    body = request.get_json(silent=True) or {}
    ssid = body.get("ssid")
    if not ssid:
        return _json({"error": "'ssid' field is required"}, 400)
    try:
        result = hardware.forget_wifi(ssid)
    except grpc.RpcError as exc:
        return _network_agent_error(exc)
    except Exception as exc:  # noqa: BLE001
        return _json({"error": str(exc)}, 500)
    return _publish_if_success(_json(result), "network_config_changed", ["network"], data=result)
