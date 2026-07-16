"""Detection controller: run state (status/start/stop), confidence thresholds,
stats and the detections snapshot."""
import logging

import grpc
from flask import Response, request

from ..grpc_clients import clients, inf, trn
from ..helpers import (
    DEVICE_VERSION,
    _accepts_protobuf,
    _grpc_error,
    _hub_verified,
    _json,
    _json_error,
    _json_success,
    _protobuf,
    _publish_if_success,
)
from . import api_bp

# Compiled detection schemas (protobuf content-negotiation for the Tauri/native
# and Leptos protobuf endpoints). Sits next to the other stubs in gateway/proto,
# which `..grpc_clients` (imported above) puts on sys.path.
import detection_pb2 as det_pb  # noqa: E402

logger = logging.getLogger(__name__)


def _camera_connected(status) -> bool:
    """Read StatusResponse.camera_connected, treating "unset" as connected.

    The field has explicit presence, so an inference-service that predates the
    camera gate leaves it absent rather than sending false. Defaulting that to
    false would fail closed — the gateway would refuse every Start with a 409
    until inference is upgraded too. Unset means "no gate on the producer",
    which is exactly the pre-gate behaviour: let detection start.
    """
    return status.camera_connected if status.HasField("camera_connected") else True


@api_bp.route('/api/v1/status', methods=['GET'])
def get_status():
    """GET /api/v1/status — gateway relay."""
    try:
        s = clients.detection.GetStatus(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if _accepts_protobuf():
        r = det_pb.StatusResponse()
        r.is_running = s.is_running
        r.current_model = s.model
        r.confidence_threshold = s.confidence_threshold
        r.stats.fps = float(s.stats.fps)
        r.stats.inference_time = float(s.stats.inference_time)
        r.stats.detections = int(s.stats.detections)
        r.stats.frames_with_detections = int(s.stats.frames_with_detections)
        r.protocols.http_port = 5000
        r.camera_connected = _camera_connected(s)
        return _protobuf(r)
    return _json({
        "is_running": s.is_running,
        "version": DEVICE_VERSION,
        "model": s.model,
        "confidence_threshold": s.confidence_threshold,
        "overlay_threshold": s.overlay_threshold,
        "acceleration_type": s.acceleration_type,
        "runtime_type": s.runtime_type,
        "camera_connected": _camera_connected(s),
        "stats": {
            "fps": s.stats.fps,
            "inference_time": s.stats.inference_time,
            "detections": s.stats.detections,
            "frames_with_detections": s.stats.frames_with_detections,
        },
        "protocols": {
            "http_port": 5000,
        },
    })


@api_bp.route('/api/v1/start', methods=['POST'])
def start_detection():
    """POST /api/v1/start — gateway relay."""
    try:
        status = clients.detection.GetStatus(inf.Empty())
        if status.is_running:
            if _accepts_protobuf():
                return _protobuf(det_pb.StartDetectionResponse(
                    success=False, message="Detection already running"), 400)
            return _json_error("Detection already running", 400)
        # Without a camera the webcam-server publishes no frames at all, so
        # detection would run blind — refuse before touching inference.
        if not _camera_connected(status):
            msg = "No camera connected. Connect a camera before starting detection."
            if _accepts_protobuf():
                return _protobuf(det_pb.StartDetectionResponse(success=False, message=msg), 409)
            return _json_error(msg, 409)
        # Training's SAM assistant must never stay GPU-pinned once detection
        # runs. Best-effort with its own except: an unreachable training-
        # service must not block the start (nor be mistaken for an inference
        # failure), and the status probe avoids a spurious sam_changed event
        # from unloading nothing.
        try:
            if clients.training.GetSamStatus(trn.Empty()).loaded:
                clients.training.UnloadSam(trn.Empty())
        except grpc.RpcError as sam_exc:
            logger.warning("Best-effort SAM unload before start failed: %s",
                           sam_exc)
        r = clients.detection.Start(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        if _accepts_protobuf():
            return _protobuf(det_pb.StartDetectionResponse(success=False, message=r.message), 500)
        return _json_error(r.message, 500)
    video_feed_url = "/api/v1/video_feed_processed"
    if _accepts_protobuf():
        resp = _protobuf(det_pb.StartDetectionResponse(
            success=True, message="Detection started", video_feed_url=video_feed_url))
    else:
        resp = _json_success(message="Detection started", video_feed_url=video_feed_url)
    return _publish_if_success(resp, "detection_state_changed", ["status"],
                               data={"is_running": True})


@api_bp.route('/api/v1/stop', methods=['POST'])
def stop_detection():
    """POST /api/v1/stop — gateway relay."""
    try:
        if not clients.detection.GetStatus(inf.Empty()).is_running:
            if _accepts_protobuf():
                return _protobuf(det_pb.StopDetectionResponse(
                    success=False, message="Detection not running"), 400)
            return _json_error("Detection not running", 400)
        clients.detection.Stop(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if _accepts_protobuf():
        resp = _protobuf(det_pb.StopDetectionResponse(success=True, message="Detection stopped"))
    else:
        resp = _json_success(message="Detection stopped")
    return _publish_if_success(resp, "detection_state_changed", ["status"],
                               data={"is_running": False})


def _parse_threshold():
    """Return (threshold, error_response). Mirrors DetectionController."""
    if "application/json" in request.headers.get("Content-Type", ""):
        try:
            threshold = (request.get_json() or {}).get("threshold")
        except Exception:  # noqa: BLE001
            return None, _json({"success": False, "message": "Invalid JSON request"}, 400)
        if threshold is None:
            return None, _json({"success": False, "message": "Missing threshold parameter"}, 400)
        return threshold, None
    req = det_pb.SetThresholdRequest()
    try:
        req.ParseFromString(request.data)
    except Exception:  # noqa: BLE001
        return None, _protobuf(det_pb.SetThresholdResponse(
            success=False, message="Invalid protobuf request"), 400)
    return req.threshold, None


def _threshold_success(threshold, message):
    """Build a threshold-set success Response (JSON or protobuf)."""
    if "application/json" in request.headers.get("Content-Type", ""):
        return _json({"success": True, "message": message, "threshold": threshold})
    return _protobuf(det_pb.SetThresholdResponse(success=True, message=message, threshold=threshold))


def _threshold_invalid():
    """Build a 400 'threshold out of range' Response (JSON or protobuf)."""
    if "application/json" in request.headers.get("Content-Type", ""):
        return _json({"success": False, "message": "Threshold must be between 0 and 1"}, 400)
    return _protobuf(det_pb.SetThresholdResponse(
        success=False, message="Threshold must be between 0 and 1"), 400)


@api_bp.route('/api/v1/threshold', methods=['POST'])
def set_threshold():
    """POST /api/v1/threshold — gateway relay."""
    threshold, err = _parse_threshold()
    if err is not None:
        return err
    if threshold is None:
        return _threshold_invalid()
    try:
        r = clients.detection.SetThreshold(inf.ThresholdRequest(threshold=float(threshold)))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _threshold_invalid()
    resp = _threshold_success(threshold, "Threshold updated")
    return _publish_if_success(resp, "thresholds_changed", ["status", "thresholds"],
                               data={"confidence_threshold": threshold})


@api_bp.route('/api/v1/overlay_threshold', methods=['POST'])
def set_overlay_threshold():
    """POST /api/v1/overlay_threshold — gateway relay."""
    threshold, err = _parse_threshold()
    if err is not None:
        return err
    if threshold is None:
        return _threshold_invalid()
    try:
        r = clients.detection.SetOverlayThreshold(inf.ThresholdRequest(threshold=float(threshold)))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _threshold_invalid()
    resp = _threshold_success(threshold, "Overlay threshold updated")
    return _publish_if_success(resp, "thresholds_changed", ["status", "thresholds"],
                               data={"overlay_threshold": threshold})


@api_bp.route('/api/v1/stats', methods=['GET'])
def get_stats():
    """GET /api/v1/stats — gateway relay."""
    try:
        s = clients.detection.GetStatus(inf.Empty()).stats
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({
        "fps": s.fps,
        "inference_time": s.inference_time,
        "detections": s.detections,
        "frames_with_detections": s.frames_with_detections,
    })


@api_bp.route('/api/v1/stats/reset', methods=['POST'])
def reset_stats():
    """POST /api/v1/stats/reset — gateway relay."""
    try:
        clients.detection.ResetStats(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    resp = _json({"success": True, "reset": "stats"})
    return _publish_if_success(resp, "stats_changed", ["stats"], data={"reset": True})


@api_bp.route('/api/v1/detections/snapshot', methods=['GET'])
def get_detections_snapshot():
    """GET /api/v1/detections/snapshot — gateway relay."""
    include_frame = request.args.get("include_frame", "true").lower() != "false"
    include_raw = request.args.get("include_raw_frame", "false").lower() == "true"
    # Hub pulls arrive through the mTLS terminator, which stamps the verified
    # client-cert result (system-vision/config/nginx-enforcing.conf). Local
    # consumers (Flow nodes hitting the gateway directly) must not feed the
    # offline-buffer's hub-is-online heartbeat, even if they spoof the header —
    # _hub_verified also checks that the peer is the terminator itself.
    hub_pull = _hub_verified()
    try:
        # proto3 bool default is false; set it explicitly to match HTTP default-true.
        r = clients.detection.Snapshot(inf.SnapshotRequest(
            include_frame=include_frame, include_raw_frame=include_raw,
            hub_pull=hub_pull))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return Response(r.json, status=200, mimetype="application/json")


@api_bp.route('/api/v1/detections/backlog', methods=['GET'])
def get_detections_backlog():
    """GET /api/v1/detections/backlog — one page of offline-buffered records."""
    limit = request.args.get("limit", type=int)
    if limit is None:
        limit = 0
    elif limit < 0:
        return _json_error('"limit" must be >= 0', 400)
    elif limit > 100:
        limit = 100
    try:
        r = clients.detection.ListBacklog(inf.BacklogRequest(limit=limit))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return Response(r.json, status=200, mimetype="application/json")


@api_bp.route('/api/v1/detections/backlog/ack', methods=['POST'])
def ack_detections_backlog():
    """POST /api/v1/detections/backlog/ack — delete records the hub persisted."""
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not all(type(i) is int for i in ids):
        return _json_error('Body must be {"ids": [int, ...]}', 400)
    try:
        r = clients.detection.AckBacklog(inf.BacklogAckRequest(ids=ids))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"success": r.success, "message": r.message})
