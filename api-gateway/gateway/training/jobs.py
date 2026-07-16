"""Training-job routes: start (with GPU-handover re-assert), status polling,
cancel and finish."""
import grpc
from flask import request

from ..grpc_clients import clients, trn
from . import training_bp
from .helpers import (
    _grpc_error,
    _job_dict,
    _json,
    _json_error,
    _release_runtime,
    _result,
)
from .orphan import tracker


@training_bp.route("/api/v1/training/train", methods=["POST"])
def training_start():
    """POST /api/v1/training/train — gateway relay."""
    body = request.get_json(silent=True) or {}
    federated = bool(body.get("federated"))
    model_name = (body.get("model_name") or "").strip()
    if not model_name and not federated:
        # Federated rounds keep the result on-device, so no name is needed.
        return _json_error("'model_name' is required")
    dataset_id = (body.get("dataset_id") or "").strip()
    if not dataset_id:
        return _json_error("'dataset_id' is required")
    # Re-assert the GPU handover: idempotent, and protects against a client
    # that skipped /training/enter.
    try:
        r = _release_runtime()
        if not r.success:
            return _json_error(r.message, 409)
    except grpc.RpcError as exc:
        detail = exc.details() if hasattr(exc, "details") else str(exc)
        return _json_error(f"Could not release inference runtime: {detail}", 503)
    try:
        job = clients.training.StartTraining(trn.TrainRequest(
            model_name=model_name,
            dataset_id=dataset_id,
            epochs=int(body.get("epochs") or 0),
            batch=int(body.get("batch") or 0),
            patience=int(body.get("patience") or 0),
            initial_weights_id=(body.get("initial_weights_id") or "").strip(),
            federated=federated,
        ))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    except (TypeError, ValueError):
        return _json_error("'epochs', 'batch' and 'patience' must be non-negative integers")
    # Covers clients that skipped /training/enter (the handover was re-asserted
    # above): a run is now active, so the orphan watchdog must be armed.
    tracker.arm()
    return _json(_job_dict(job), 202)


@training_bp.route("/api/v1/training/train/status", methods=["GET"])
def training_status():
    """GET /api/v1/training/train/status — gateway relay."""
    try:
        job = clients.training.GetTraining(trn.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json(_job_dict(job))


@training_bp.route("/api/v1/training/train/cancel", methods=["POST"])
def training_cancel():
    """POST /api/v1/training/train/cancel — gateway relay."""
    try:
        return _result(clients.training.CancelTraining(trn.Empty()))
    except grpc.RpcError as exc:
        return _grpc_error(exc)


@training_bp.route("/api/v1/training/train/finish", methods=["POST"])
def training_finish():
    """POST /api/v1/training/train/finish — gateway relay."""
    try:
        return _result(clients.training.FinishTraining(trn.Empty()))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
