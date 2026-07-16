"""Camera controller: the two MJPEG feeds (SHM fan-out) and camera device
listing/configuration."""
import json

import grpc
from flask import Response, request

from .. import media
from ..grpc_clients import clients, inf
from ..helpers import (
    _grpc_error,
    _json_error,
    _json_success,
    _publish_if_success,
    _response_json,
)
from . import api_bp


@api_bp.route('/api/v1/video_feed', methods=['GET'])
def video_feed():
    """GET /api/v1/video_feed — gateway relay."""
    return Response(media.generate_raw(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@api_bp.route('/api/v1/video_feed_processed', methods=['GET'])
def video_feed_processed():
    """GET /api/v1/video_feed_processed — gateway relay."""
    return Response(media.generate_processed(),
                    mimetype="multipart/x-mixed-replace; boundary=frame")


@api_bp.route('/api/v1/camera/devices', methods=['GET'])
def get_camera_devices():
    """GET /api/v1/camera/devices — gateway relay."""
    try:
        r = clients.management.GetCamera(inf.Empty())
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    return Response(r.json, status=200, mimetype="application/json")


@api_bp.route('/api/v1/camera/config', methods=['POST'])
def update_camera_config():
    """POST /api/v1/camera/config — gateway relay."""
    data = request.get_json(silent=True)
    if not data:
        return _json_error("No data provided")
    try:
        r = clients.management.UpdateCamera(inf.ConfigJson(json=json.dumps(data)))
    except grpc.RpcError as exc:
        return _grpc_error(exc)
    if not r.success:
        return _json_error(r.message, 400)
    resp = _json_success(r.message)
    return _publish_if_success(resp, "camera_config_changed", ["camera"], data=_response_json(resp))
