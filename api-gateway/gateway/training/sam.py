"""SAM (Segment Anything) assisted-labeling routes: status, load/unload of the
checkpoint and point/text-prompted segmentation."""
import grpc
from flask import request

from ..grpc_clients import clients, trn
from . import training_bp
from .helpers import _grpc_error, _json, _json_error, _result


@training_bp.route("/api/v1/training/sam", methods=["GET"])
def training_sam_status():
    """GET /api/v1/training/sam — gateway relay."""
    try:
        s = clients.training.GetSamStatus(trn.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"available": s.available, "loaded": s.loaded, "message": s.message})


@training_bp.route("/api/v1/training/sam/load", methods=["POST"])
def training_sam_load():
    """POST /api/v1/training/sam/load — gateway relay."""
    try:
        # Cold load reads the multi-GB checkpoint; allow well beyond the
        # default control-call deadline.
        return _result(clients.training.LoadSam(trn.Empty(), timeout=300))
    except grpc.RpcError as exc:
        return _grpc_error(exc)


@training_bp.route("/api/v1/training/sam/unload", methods=["POST"])
def training_sam_unload():
    """POST /api/v1/training/sam/unload — gateway relay."""
    try:
        return _result(clients.training.UnloadSam(trn.Empty()))
    except grpc.RpcError as exc:
        return _grpc_error(exc)


@training_bp.route("/api/v1/training/sam/segment", methods=["POST"])
def training_sam_segment():
    """POST /api/v1/training/sam/segment — gateway relay."""
    body = request.get_json(silent=True) or {}
    image_id = body.get("image_id", "")
    dataset_id = body.get("dataset_id", "")
    if not image_id:
        return _json_error("'image_id' is required")
    if not dataset_id:
        return _json_error("'dataset_id' is required")
    points = body.get("points") or []
    if not isinstance(points, list) or not all(isinstance(p, dict) for p in points):
        return _json_error("'points' must be a list of objects")
    try:
        msg = trn.SamRequest(
            image_id=image_id,
            dataset_id=dataset_id,
            text_prompt=str(body.get("text_prompt", "") or ""),
            threshold=float(body.get("threshold", 0.0) or 0.0),
            points=[
                trn.Point(x=float(p.get("x", 0)), y=float(p.get("y", 0)),
                          positive=bool(p.get("positive", True)))
                for p in points
            ],
        )
    except (TypeError, ValueError):
        return _json_error("Malformed point entry or threshold")
    try:
        r = clients.training.SamSegment(msg, timeout=300)
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 400)
    return _json({
        "boxes": [{"cx": b.cx, "cy": b.cy, "w": b.w, "h": b.h} for b in r.boxes],
        "scores": list(r.scores),
    })
