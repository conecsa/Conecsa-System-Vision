"""Shared helpers for the training routes: JSON responses, gRPC error mapping
and message↔dict serializers."""
import json
import logging

import grpc
from flask import Response

from ..grpc_clients import clients, inf, trn

logger = logging.getLogger(__name__)


def _json(data, status=200) -> Response:
    """Build a JSON Response with the given body and status."""
    return Response(json.dumps(data), status=status, mimetype="application/json")


def _json_error(message, status=400) -> Response:
    """Build a JSON ``{"error": message}`` Response (default 400)."""
    return _json({"error": message}, status)


def _grpc_error(exc: grpc.RpcError) -> Response:
    """Map a training-service gRPC error to a JSON Response."""
    detail = exc.details() if hasattr(exc, "details") else str(exc)
    code = exc.code() if hasattr(exc, "code") else None
    if code == grpc.StatusCode.NOT_FOUND:
        return _json_error(detail, 404)
    if code == grpc.StatusCode.FAILED_PRECONDITION:
        return _json_error(detail, 409)
    if code == grpc.StatusCode.INVALID_ARGUMENT:
        return _json_error(detail, 400)
    status = 503 if code in (grpc.StatusCode.UNAVAILABLE,
                             grpc.StatusCode.DEADLINE_EXCEEDED) else 500
    logger.error("training RPC failed: %s", detail)
    return _json_error(f"Training service error: {detail}", status)


def _result(r, ok_status=200) -> Response:
    """Map a training Result message to a JSON success/error Response."""
    if not r.success:
        return _json_error(r.message or "Operation failed (no detail reported)", 400)
    return _json({"status": "success", "message": r.message}, ok_status)


def _job_dict(job) -> dict:
    """Serialize a training job (status + metrics) to its JSON dict."""
    try:
        metrics = json.loads(job.metrics_json) if job.metrics_json else {}
    except ValueError:
        metrics = {}
    return {
        "job_id": job.job_id,
        "status": job.status or "idle",
        "progress": job.progress,
        "epoch": job.epoch,
        "total_epochs": job.total_epochs,
        "message": job.message,
        "error": job.error,
        "model_name": job.model_name,
        "conversion_job_id": job.conversion_job_id,
        "metrics": metrics,
        "started_at": job.started_at,
        "dataset_id": job.dataset_id,
        "federated": job.federated,
        "result_weights_id": job.result_weights_id,
    }


def _meta_dict(m) -> dict:
    """Serialize a dataset's metadata to its JSON dict."""
    return {
        "dataset_id": m.dataset_id,
        "name": m.name,
        "created_at": m.created_at,
        "cover_image_id": m.cover_image_id,
        "image_count": m.image_count,
        "labeled_count": m.labeled_count,
        "class_count": m.class_count,
    }


def _parse_named_boxes(raw: str) -> list:
    """Parse the multipart ``boxes`` field into NamedBox messages.

    Expects a JSON list of ``{"class_name", "x1", "y1", "x2", "y2"}``; raises
    ``ValueError`` with a client-facing message on any malformed entry.
    """
    try:
        data = json.loads(raw or "[]")
    except ValueError:
        raise ValueError("'boxes' must be valid JSON")
    if not isinstance(data, list):
        raise ValueError("'boxes' must be a JSON list")
    if not all(isinstance(b, dict) for b in data):
        raise ValueError("Malformed box entry")
    try:
        return [
            trn.NamedBox(class_name=str(b.get("class_name", "")),
                         x1=float(b.get("x1", 0)), y1=float(b.get("y1", 0)),
                         x2=float(b.get("x2", 0)), y2=float(b.get("y2", 0)))
            for b in data
        ]
    except (TypeError, ValueError):
        raise ValueError("Malformed box entry")


def _release_runtime() -> "inf.Result":
    """Release the inference GPU runtime (GPU handover to training)."""
    return clients.management.ReleaseRuntime(inf.Empty())
