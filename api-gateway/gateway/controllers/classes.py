"""Class-labels controller: get/upload/clear, with JSON↔protobuf content
negotiation."""
import grpc
from flask import request

from ..grpc_clients import clients, inf
from ..helpers import (
    _grpc_error,
    _json,
    _protobuf,
    _publish_event,
    _should_use_json,
)
from . import api_bp

# Compiled detection schemas (protobuf content-negotiation). Sits next to the
# other stubs in gateway/proto, which `..grpc_clients` (imported above) puts on
# sys.path.
import detection_pb2 as det_pb  # noqa: E402


def _classes_response(success, message, classes, status_code, content_type_check=False):
    """Build a classes Response (JSON or the negotiated protobuf message)."""
    use_json = _should_use_json(content_type_check)
    if use_json:
        return _json({"success": success, "message": message, "classes": classes}, status_code)
    msg = (det_pb.UploadClassesResponse() if content_type_check
           else det_pb.GetClassesResponse())
    msg.success = success
    msg.message = message
    if classes:
        msg.classes.extend(classes)
    return _protobuf(msg, status_code)


@api_bp.route('/api/v1/classes', methods=['GET'])
def get_classes():
    """GET /api/v1/classes — gateway relay."""
    try:
        cl = clients.management.GetClasses(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _classes_response(True, "Classes retrieved successfully", list(cl.classes), 200)


@api_bp.route('/api/v1/classes', methods=['POST'])
def upload_classes():
    """POST /api/v1/classes — gateway relay."""
    use_json = _should_use_json(check_content_type=True)
    if use_json:
        try:
            data = request.get_json()
            if not data or "classes" not in data:
                return _classes_response(False, "Invalid JSON: 'classes' field required", [], 400, True)
            labels = data["classes"]
            if not isinstance(labels, list):
                return _classes_response(False, "'classes' must be an array", [], 400, True)
        except Exception as exc:  # noqa: BLE001
            return _classes_response(False, f"Invalid JSON: {exc}", [], 400, True)
    else:
        req = det_pb.UploadClassesRequest()
        try:
            req.ParseFromString(request.data)
        except Exception:  # noqa: BLE001
            return _classes_response(False, "Invalid protobuf request", [], 400, True)
        labels = [line.strip() for line in req.classes_content.split("\n") if line.strip()]

    if not labels:
        return _classes_response(False, "No valid classes found", [], 400, True)

    try:
        r = clients.management.SetClasses(inf.ClassList(classes=labels))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _classes_response(False, "Failed to save classes", [], 500, True)

    resp = _classes_response(True, f"Successfully uploaded {len(labels)} classes", labels, 200, True)
    _publish_event("classes_changed", ["classes"], data={"count": len(labels)})
    return resp


@api_bp.route('/api/v1/classes', methods=['DELETE'])
def clear_classes():
    """DELETE /api/v1/classes — gateway relay."""
    try:
        r = clients.management.ClearClasses(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _classes_response(False, "Failed to clear classes", [], 500, True)
    resp = _classes_response(True, "Classes cleared successfully", [], 200, True)
    _publish_event("classes_changed", ["classes"], data={"count": 0})
    return resp
