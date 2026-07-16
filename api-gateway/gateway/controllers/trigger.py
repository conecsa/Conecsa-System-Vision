"""Trigger/counter controller: the detection trigger switch and the detection
counter."""
import grpc

from ..grpc_clients import clients, inf
from ..helpers import _grpc_error, _json, _publish_if_success
from . import api_bp


@api_bp.route('/api/v1/trigger/status', methods=['GET'])
def get_trigger_status():
    """GET /api/v1/trigger/status — gateway relay."""
    try:
        c = clients.detection.GetCounter(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"trigger_enabled": c.trigger_enabled, "detection_count": c.count})


@api_bp.route('/api/v1/trigger/enable', methods=['POST'])
def enable_trigger():
    """POST /api/v1/trigger/enable — gateway relay."""
    try:
        clients.detection.EnableTrigger(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    resp = _json({"success": True, "trigger_enabled": True})
    return _publish_if_success(resp, "trigger_changed", ["trigger"], data={"trigger_enabled": True})


@api_bp.route('/api/v1/trigger/disable', methods=['POST'])
def disable_trigger():
    """POST /api/v1/trigger/disable — gateway relay."""
    try:
        clients.detection.DisableTrigger(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    resp = _json({"success": True, "trigger_enabled": False})
    return _publish_if_success(resp, "trigger_changed", ["trigger"], data={"trigger_enabled": False})


@api_bp.route('/api/v1/counter', methods=['GET'])
def get_counter():
    """GET /api/v1/counter — gateway relay."""
    try:
        c = clients.detection.GetCounter(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"count": c.count, "trigger_enabled": c.trigger_enabled})


@api_bp.route('/api/v1/counter/reset', methods=['POST'])
def reset_counter():
    """POST /api/v1/counter/reset — gateway relay."""
    try:
        clients.detection.ResetCounter(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    resp = _json({"success": True, "count": 0})
    return _publish_if_success(resp, "counter_changed", ["trigger"], data={"count": 0})
