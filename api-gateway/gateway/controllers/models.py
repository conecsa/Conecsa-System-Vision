"""Model controller: listing, upload (with conversion tracking), selection,
deletion and download."""
import json
import logging
import os

import grpc
from flask import Response, request

from ..grpc_clients import clients, inf
from ..helpers import (
    _grpc_error,
    _json,
    _json_error,
    _json_success,
    _publish_event,
    _publish_if_success,
    _response_json,
)
from . import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/api/v1/models', methods=['GET'])
def list_models():
    """GET /api/v1/models — gateway relay."""
    try:
        ml = clients.model.ListModels(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"models": [
        {"name": m.name, "size": m.size, "modified": m.modified, "is_active": m.is_active}
        for m in ml.models
    ]})


def _upload_stream(filename, imgsz, file_stream):
    """Yield ModelChunk messages (metadata first, then file chunks) for the upload RPC."""
    yield inf.ModelChunk(meta=inf.ModelUploadMeta(filename=filename, imgsz=imgsz))
    while True:
        chunk = file_stream.read(1 << 20)
        if not chunk:
            break
        yield inf.ModelChunk(chunk=chunk)


@api_bp.route('/api/v1/model', methods=['POST'])
def upload_model():
    """POST /api/v1/model — gateway relay."""
    if "file" not in request.files:
        return _json_error("No file provided")
    file = request.files["file"]
    try:
        imgsz = int(request.form.get("imgsz", 640))
    except (TypeError, ValueError):
        imgsz = 640
    try:
        result = clients.model.UploadModel(
            _upload_stream(file.filename, imgsz, file.stream))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    try:
        body = json.loads(result.json) if result.json else {}
    except ValueError:
        body = {}
    resp = _json(body, result.http_status)
    if resp.status_code < 400:
        status = body.get("status", "")
        if status == "converting":
            _publish_event("conversion_started", ["models", "conversion"], data=body)
        else:
            _publish_event("model_changed",
                           ["models", "status", "classes", "areas", "thresholds", "camera"],
                           data=body)
    return resp


@api_bp.route('/api/v1/model/select', methods=['POST'])
def select_model():
    """POST /api/v1/model/select — gateway relay."""
    data = request.get_json(silent=True)
    if not data or "model_name" not in data:
        return _json_error("Missing model_name parameter")
    model_name = data["model_name"]
    try:
        was_running = clients.detection.GetStatus(inf.Empty()).is_running
        r = clients.model.SelectModel(inf.ModelName(name=model_name))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 404 if "not found" in r.message else 500)
    resp = _json_success(message="Model selected and loaded successfully",
                         model=model_name, path=r.message, was_running=was_running)
    return _publish_if_success(
        resp, "model_changed",
        ["status", "models", "classes", "areas", "thresholds", "camera"],
        data=_response_json(resp))


@api_bp.route('/api/v1/model/conversion', methods=['GET'])
def list_active_conversions():
    """GET /api/v1/model/conversion — gateway relay."""
    try:
        cl = clients.model.ListConversions(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return _json({"jobs": [_conversion_dict(j) for j in cl.jobs]})


@api_bp.route('/api/v1/model/conversion/<job_id>', methods=['GET'])
def get_conversion_status(job_id):
    """GET /api/v1/model/conversion/<job_id> — gateway relay."""
    try:
        job = clients.model.GetConversion(inf.ConversionId(job_id=job_id))
    except grpc.RpcError as exc:
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            return _json_error(f"Conversion job '{job_id}' not found", 404)
        return _grpc_error(exc)
    data = _conversion_dict(job)
    if job.status == "done" and job.engine_filename:
        data["auto_select_hint"] = job.engine_filename
    return _json(data)


def _conversion_dict(job) -> dict:
    """Serialize a conversion job to its JSON dict."""
    return {
        "job_id": job.job_id,
        "original_filename": job.original_filename,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "engine_filename": job.engine_filename,
        "started_at": job.started_at,
    }


@api_bp.route('/api/v1/model/<model_name>', methods=['DELETE'])
def delete_model(model_name):
    """DELETE /api/v1/model/<model_name> — gateway relay."""
    if not model_name:
        return _json_error("Missing model_name parameter")
    try:
        r = clients.model.DeleteModel(inf.ModelName(name=model_name))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 404 if "not found" in r.message.lower() else 500)
    resp = _json_success(message=f"Model '{model_name}' deleted successfully")
    return _publish_if_success(resp, "models_changed", ["models"], data={"model": model_name})


@api_bp.route('/api/v1/model/<model_name>/download', methods=['GET'])
def download_model(model_name):
    """GET /api/v1/model/<model_name>/download — gateway relay."""
    stream = clients.model.DownloadModel(inf.ModelName(name=model_name), timeout=600)
    # Pull the first chunk before answering: a NOT_FOUND raises here, while
    # the HTTP status can still be set (streamed bodies can't change it later).
    try:
        first = next(stream, None)
    except grpc.RpcError as exc:
        if exc.code() == grpc.StatusCode.NOT_FOUND:
            return _json_error(f"Model '{model_name}' not found", 404)
        return _grpc_error(exc)

    def generate():
        """Yield the model file bytes relayed from the inference-service."""
        try:
            if first is not None:
                yield first.chunk
            for msg in stream:
                yield msg.chunk
        except grpc.RpcError as exc:
            logger.warning("DownloadModel stream aborted: %s", exc)
            return

    # Names are validated basenames server-side; also strip header-unsafe characters defensively.
    safe_name = os.path.basename(model_name).replace('"', '').replace('\r', '').replace('\n', '')
    return Response(
        generate(),
        mimetype="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "no-store",
        },
    )
