"""Federated-weights routes (hub-orchestrated FedAvg): checkpoint upload,
download, deletion and CPU-side averaging."""
import logging

import grpc
from flask import Response, request

from ..grpc_clients import clients, trn
from . import training_bp
from .helpers import _grpc_error, _json, _json_error, _result

logger = logging.getLogger(__name__)


@training_bp.route("/api/v1/training/weights", methods=["POST"])
def training_weights_upload():
    """POST /api/v1/training/weights — gateway relay."""
    if "file" not in request.files:
        return _json_error("No file provided")
    file = request.files["file"]

    def stream():
        """Yield WeightsChunk messages (metadata first, then .pt chunks)."""
        yield trn.WeightsChunk(meta=trn.WeightsUploadMeta(name=file.filename or ""))
        while True:
            chunk = file.stream.read(1 << 20)
            if not chunk:
                break
            yield trn.WeightsChunk(chunk=chunk)

    try:
        r = clients.training.UploadWeights(stream(), timeout=300)
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 400)
    return _json({"weights_id": r.weights_id, "size": r.size}, 201)


@training_bp.route("/api/v1/training/weights/<weights_id>", methods=["GET"])
def training_weights_download(weights_id):
    """GET /api/v1/training/weights/<weights_id> — gateway relay."""
    stream = clients.training.DownloadWeights(
        trn.WeightsId(weights_id=weights_id), timeout=600)
    # Pull the first chunk before answering: a NOT_FOUND raises here, while
    # the HTTP status can still be set (streamed bodies can't change it later).
    try:
        first = next(stream, None)
    except grpc.RpcError as exc:
        return _grpc_error(exc)

    def generate():
        """Yield the checkpoint bytes relayed from the training-service."""
        try:
            if first is not None:
                yield first.chunk
            for msg in stream:
                yield msg.chunk
        except grpc.RpcError as exc:
            logger.warning("DownloadWeights stream aborted: %s", exc)
            return

    return Response(
        generate(),
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{weights_id}.pt"',
            "Cache-Control": "no-store",
        },
    )


@training_bp.route("/api/v1/training/weights/<weights_id>", methods=["DELETE"])
def training_weights_delete(weights_id):
    """DELETE /api/v1/training/weights/<weights_id> — gateway relay."""
    try:
        return _result(clients.training.DeleteWeights(
            trn.WeightsId(weights_id=weights_id)))
    except grpc.RpcError as exc:
        return _grpc_error(exc)


@training_bp.route("/api/v1/training/weights/average", methods=["POST"])
def training_weights_average():
    """POST /api/v1/training/weights/average — gateway relay."""
    body = request.get_json(silent=True) or {}
    weights_ids = body.get("weights_ids")
    if not isinstance(weights_ids, list) or len(weights_ids) < 2 or \
            not all(isinstance(i, str) and i for i in weights_ids):
        return _json_error("'weights_ids' must be a list of at least two ids")
    try:
        r = clients.training.AverageWeights(
            trn.AverageRequest(weights_ids=weights_ids), timeout=300)
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 400)
    return _json({"weights_id": r.weights_id})
