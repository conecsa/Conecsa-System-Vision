"""Detection-areas controller: CRUD, shape selection and move/resize commands
on the inference-service's detection areas."""
import grpc
from flask import Response, request

from ..grpc_clients import clients, inf
from ..helpers import _grpc_error, _json, _publish_if_success, _response_json
from . import api_bp

VALID_SHAPES = {"rectangle", "circle"}
VALID_ACTIONS = {
    "move_up", "move_down", "move_left", "move_right",
    "grow", "shrink",
    "grow_horizontal", "shrink_horizontal",
    "grow_vertical", "shrink_vertical",
}


def _area_state(r, status=200) -> Response:
    """Wrap a detection-area state JSON blob in a Response."""
    return Response(r.state_json, status=status, mimetype="application/json")


def _area_op(rpc, status=200):
    """Run a detection-area RPC and return its state JSON (or a gRPC error)."""
    try:
        r = rpc()
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.ok:
        return _json({"error": "area not found"}, 404)
    resp = _area_state(r, status)
    return _publish_if_success(resp, "detection_areas_changed", ["areas"])


@api_bp.route('/api/v1/detection-areas', methods=['GET'])
def list_detection_areas():
    """GET /api/v1/detection-areas — gateway relay."""
    try:
        r = clients.management.ListAreas(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _area_state(r)


@api_bp.route('/api/v1/detection-areas', methods=['POST'])
def create_detection_area():
    """POST /api/v1/detection-areas — gateway relay."""
    try:
        r = clients.management.CreateArea(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    resp = _area_state(r, 201)
    return _publish_if_success(resp, "detection_areas_changed", ["areas"], data=_response_json(resp))


@api_bp.route('/api/v1/detection-areas/<area_id>', methods=['DELETE'])
def delete_detection_area(area_id):
    """DELETE /api/v1/detection-areas/<area_id> — gateway relay."""
    return _area_op(lambda: clients.management.DeleteArea(inf.AreaId(area_id=area_id)))


@api_bp.route('/api/v1/detection-areas/<area_id>/save', methods=['POST'])
def save_detection_area(area_id):
    """POST /api/v1/detection-areas/<area_id>/save — gateway relay."""
    return _area_op(lambda: clients.management.SaveArea(inf.AreaId(area_id=area_id)))


@api_bp.route('/api/v1/detection-areas/<area_id>/edit', methods=['POST'])
def edit_detection_area(area_id):
    """POST /api/v1/detection-areas/<area_id>/edit — gateway relay."""
    return _area_op(lambda: clients.management.EditArea(inf.AreaId(area_id=area_id)))


@api_bp.route('/api/v1/detection-areas/<area_id>/discard', methods=['POST'])
def discard_detection_area(area_id):
    """POST /api/v1/detection-areas/<area_id>/discard — gateway relay."""
    return _area_op(lambda: clients.management.DiscardArea(inf.AreaId(area_id=area_id)))


@api_bp.route('/api/v1/detection-areas/<area_id>/shape', methods=['POST'])
def set_detection_area_shape(area_id):
    """POST /api/v1/detection-areas/<area_id>/shape — gateway relay."""
    data = request.get_json(silent=True) or {}
    shape = data.get("shape")
    if shape not in VALID_SHAPES:
        return _json({"error": f"invalid shape; expected one of {sorted(VALID_SHAPES)}"}, 400)
    return _area_op(lambda: clients.management.SetAreaShape(
        inf.AreaShape(area_id=area_id, shape=shape)))


@api_bp.route('/api/v1/detection-areas/<area_id>/command', methods=['POST'])
def detection_area_command(area_id):
    """POST /api/v1/detection-areas/<area_id>/command — gateway relay."""
    data = request.get_json(silent=True) or {}
    action = data.get("action")
    if action not in VALID_ACTIONS:
        return _json({"error": f"invalid action; expected one of {sorted(VALID_ACTIONS)}"}, 400)
    return _area_op(lambda: clients.management.AreaCommand(
        inf.AreaCommandRequest(area_id=area_id, action=action)))
