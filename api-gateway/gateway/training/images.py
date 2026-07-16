"""Per-image routes: camera capture, labeled-image upload, listing, JPEG
retrieval, deletion, replication and the YOLO label editor."""
import grpc
from flask import Response, request

from ..grpc_clients import clients, trn
from . import training_bp
from .helpers import _grpc_error, _json, _json_error, _parse_named_boxes, _result


@training_bp.route("/api/v1/training/datasets/<dataset_id>/capture", methods=["POST"])
def training_capture(dataset_id):
    """POST /api/v1/training/datasets/<dataset_id>/capture — gateway relay."""
    try:
        info = clients.training.CaptureImage(trn.DatasetId(dataset_id=dataset_id))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({
        "image_id": info.image_id,
        "created_at": info.created_at,
        "labeled": info.labeled,
        "box_count": info.box_count,
        "replica": info.replica,
    })


@training_bp.route("/api/v1/training/datasets/<dataset_id>/images", methods=["POST"])
def training_image_add(dataset_id):
    """POST /api/v1/training/datasets/<dataset_id>/images — gateway relay."""
    if "file" not in request.files:
        return _json_error("No file provided")
    try:
        boxes = _parse_named_boxes(request.form.get("boxes", "[]"))
    except ValueError as exc:
        return _json_error(str(exc))
    try:
        info = clients.training.AddDatasetImage(trn.LabeledImageUpload(
            dataset_id=dataset_id,
            jpeg=request.files["file"].read(),
            boxes=boxes,
        ))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({
        "image_id": info.image_id,
        "created_at": info.created_at,
        "labeled": info.labeled,
        "box_count": info.box_count,
        "replica": info.replica,
    }, 201)


@training_bp.route("/api/v1/training/datasets/<dataset_id>/images", methods=["GET"])
def training_images(dataset_id):
    """GET /api/v1/training/datasets/<dataset_id>/images — gateway relay."""
    try:
        lst = clients.training.ListImages(trn.DatasetId(dataset_id=dataset_id))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"images": [
        {"image_id": i.image_id, "created_at": i.created_at,
         "labeled": i.labeled, "box_count": i.box_count, "replica": i.replica}
        for i in lst.images
    ]})


@training_bp.route("/api/v1/training/datasets/<dataset_id>/images/<image_id>",
                   methods=["GET"])
def training_image(dataset_id, image_id):
    """GET /api/v1/training/datasets/<dataset_id>/images/<image_id> — gateway relay."""
    try:
        blob = clients.training.GetImage(
            trn.ImageId(dataset_id=dataset_id, image_id=image_id))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return Response(blob.jpeg, mimetype="image/jpeg",
                    headers={"Cache-Control": "max-age=3600"})


@training_bp.route("/api/v1/training/datasets/<dataset_id>/images/<image_id>",
                   methods=["DELETE"])
def training_image_delete(dataset_id, image_id):
    """DELETE /api/v1/training/datasets/<dataset_id>/images/<image_id> — gateway relay."""
    try:
        return _result(clients.training.DeleteImage(
            trn.ImageId(dataset_id=dataset_id, image_id=image_id)))
    except grpc.RpcError as exc:
        return _grpc_error(exc)


@training_bp.route("/api/v1/training/datasets/<dataset_id>/images/<image_id>/replicate",
                   methods=["POST"])
def training_image_replicate(dataset_id, image_id):
    """POST /api/v1/training/datasets/<dataset_id>/images/<image_id>/replicate — gateway relay."""
    body = request.get_json(silent=True) or {}
    try:
        count = int(body.get("count", 1))
    except (TypeError, ValueError):
        return _json_error("'count' must be an integer")
    if not 1 <= count <= 50:
        return _json_error("'count' must be between 1 and 50")
    try:
        return _result(clients.training.ReplicateImage(
            trn.ReplicateRequest(dataset_id=dataset_id, image_id=image_id, count=count)))
    except grpc.RpcError as exc:
        return _grpc_error(exc)


# ── labels ─────────────────────────────────────────────────────────────────────

@training_bp.route("/api/v1/training/datasets/<dataset_id>/images/<image_id>/labels",
                   methods=["GET"])
def training_labels_get(dataset_id, image_id):
    """GET /api/v1/training/datasets/<dataset_id>/images/<image_id>/labels — gateway relay."""
    try:
        labels = clients.training.GetLabels(
            trn.ImageId(dataset_id=dataset_id, image_id=image_id))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"image_id": labels.image_id, "boxes": [
        {"class_id": b.class_id, "cx": b.cx, "cy": b.cy, "w": b.w, "h": b.h}
        for b in labels.boxes
    ]})


@training_bp.route("/api/v1/training/datasets/<dataset_id>/images/<image_id>/labels",
                   methods=["PUT"])
def training_labels_put(dataset_id, image_id):
    """PUT /api/v1/training/datasets/<dataset_id>/images/<image_id>/labels — gateway relay."""
    body = request.get_json(silent=True) or {}
    boxes = body.get("boxes")
    if not isinstance(boxes, list):
        return _json_error("Body must contain a 'boxes' list")
    if not all(isinstance(b, dict) for b in boxes):
        return _json_error("Malformed box entry")
    try:
        msg = trn.Labels(dataset_id=dataset_id, image_id=image_id, boxes=[
            trn.Box(class_id=int(b.get("class_id", 0)),
                    cx=float(b.get("cx", 0)), cy=float(b.get("cy", 0)),
                    w=float(b.get("w", 0)), h=float(b.get("h", 0)))
            for b in boxes
        ])
    except (TypeError, ValueError):
        return _json_error("Malformed box entry")
    try:
        return _result(clients.training.SetLabels(msg))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
