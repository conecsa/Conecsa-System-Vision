"""Training session lifecycle: GPU handover (enter/exit) and the CPU-only
combined camera preview."""
import logging

import grpc
from flask import Response, request

from .. import media
from ..events import event_service
from ..grpc_clients import clients, inf, trn
from . import training_bp
from .helpers import _grpc_error, _json, _json_error, _release_runtime
from .orphan import tracker

logger = logging.getLogger(__name__)


def _do_exit(resume_detection: bool) -> tuple[bool, str]:
    """Exit training mode: best-effort SAM unload, then resume (or skip).

    Shared by the /training/exit route and the orphan watchdog. Returns
    ``(success, message)``; raises ``grpc.RpcError`` when the resume RPC
    itself fails (callers map/log it).
    """
    # Best-effort SAM unload first; freeing inference is what matters.
    try:
        clients.training.UnloadSam(trn.Empty())
    except grpc.RpcError as exc:
        logger.warning("UnloadSam on exit failed: %s", exc)

    if not resume_detection:
        event_service.publish("detection_state_changed", keys=["status"],
                              data={"is_running": False})
        return True, "Inference left stopped for model conversion"

    r = clients.management.ResumeRuntime(inf.Empty())
    if not r.success:
        return False, r.message
    event_service.publish("detection_state_changed", keys=["status"],
                          data={"is_running": True})
    return True, r.message


@training_bp.route("/api/v1/training/enter", methods=["POST"])
def training_enter():
    """POST /api/v1/training/enter — gateway relay."""
    try:
        r = _release_runtime()
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 409)
    event_service.publish("detection_state_changed", keys=["status"],
                          data={"is_running": False})
    tracker.arm()
    return _json({"status": "success", "message": r.message})


@training_bp.route("/api/v1/training/exit", methods=["POST"])
def training_exit():
    # `resume_detection` (default true): a manual exit restores inference. When
    # training just finished, the client passes false — the model is being
    # converted/optimized, so the runtime stays released (GPU free for the
    # TensorRT build, old model not running). The conversion's auto-select then
    # loads the new engine with detection still stopped, for the user to start.
    """POST /api/v1/training/exit — gateway relay."""
    body = request.get_json(silent=True) or {}
    resume_detection = bool(body.get("resume_detection", True))

    try:
        ok, message = _do_exit(resume_detection)
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not ok:
        # Still in training mode — keep the orphan watchdog armed.
        return _json_error(message, 500)
    tracker.disarm()
    return _json({"status": "success", "message": message})


@training_bp.route("/api/v1/training/heartbeat", methods=["POST"])
def training_heartbeat():
    """POST /api/v1/training/heartbeat — keep the orphan watchdog fed.

    The device UI beats every ~10s while the training page is mounted; the
    blueprint-level before_request hook (tracker.touch) is the entire effect,
    which lets TRAINING_ORPHAN_TIMEOUT_SEC be short without auto-exiting a
    user who is quietly labeling. Deliberately does NOT arm the tracker: an
    in-flight beat racing a normal exit would re-arm it and fire a spurious
    resume later. (Known pre-existing gap, unchanged: after a gateway restart
    with no active job, _recover leaves the tracker disarmed.) The JSON body
    exists because the frontend transport parses every response as JSON —
    deliberately not a 204."""
    return _json({"status": "ok"})


@training_bp.route("/api/v1/training/preview", methods=["GET"])
def training_preview():
    """GET /api/v1/training/preview — gateway relay."""
    return Response(media.generate_training_preview(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")
