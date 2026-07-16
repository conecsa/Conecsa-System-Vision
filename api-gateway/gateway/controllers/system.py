"""System controller: inference config get/put, the health probe, host metrics
and host power actions (shutdown/restart via the os hardware agent)."""
import json
import logging

import grpc
from flask import Response, request

from .. import hardware
from ..grpc_clients import clients, inf
from ..helpers import (
    DEVICE_VERSION,
    _grpc_error,
    _json,
    _json_error,
    _json_success,
    _publish_if_success,
    _response_json,
)
from . import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/api/v1/config', methods=['GET'])
def get_config():
    """GET /api/v1/config — gateway relay."""
    try:
        r = clients.management.GetConfig(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return Response(r.json, status=200, mimetype="application/json")


@api_bp.route('/api/v1/config', methods=['PUT'])
def update_config():
    """PUT /api/v1/config — gateway relay."""
    data = request.get_json(silent=True)
    try:
        r = clients.management.UpdateConfig(inf.ConfigJson(json=json.dumps(data or {})))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 400)
    resp = _json_success(r.message)
    return _publish_if_success(resp, "config_changed", ["status", "thresholds", "camera"],
                               data=_response_json(resp))


@api_bp.route('/api/v1/health', methods=['GET'])
def health_check():
    """GET /api/v1/health — gateway relay."""
    return _json({"status": "healthy", "version": DEVICE_VERSION})


@api_bp.route('/api/system/status', methods=['GET'])
def get_system_status():
    # Host metrics come from the os hardware agent (it owns host introspection).
    """GET /api/system/status — gateway relay."""
    try:
        return _json(hardware.get_system_status())
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting system status: %s", exc)
        return _json({"error": str(exc)}, 500)


@api_bp.route('/api/v1/system/power', methods=['POST'])
def system_power():
    """Shut down or restart the controller host.

    Body: ``{"action": "shutdown" | "restart"}``
    """
    body = request.get_json(silent=True) or {}
    action = (body.get("action") or "").strip().lower()
    if action not in ("shutdown", "restart"):
        return _json_error("'action' must be 'shutdown' or 'restart'", 400)
    try:
        result = hardware.system_power(action)
        if not result.get("success"):
            return _json(result, 500)
        return _json(result)
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error executing system power action %s: %s", action, exc)
        return _json({"error": str(exc)}, 500)
