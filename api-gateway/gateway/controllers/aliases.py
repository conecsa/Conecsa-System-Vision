"""Simplified /api/* aliases used by the web frontend — thin wrappers around
the canonical /api/v1/* handlers."""
import json

from ..helpers import _json
from . import api_bp
from .classes import get_classes, upload_classes
from .detection import (
    get_status,
    set_overlay_threshold,
    set_threshold,
    start_detection,
    stop_detection,
)
from .models import list_models
from .system import health_check


@api_bp.route('/api/status', methods=['GET'])
def get_status_simple():
    """GET /api/status — gateway relay."""
    return get_status()


@api_bp.route('/api/start', methods=['POST'])
def start_detection_simple():
    """POST /api/start — gateway relay."""
    return start_detection()


@api_bp.route('/api/stop', methods=['POST'])
def stop_detection_simple():
    """POST /api/stop — gateway relay."""
    return stop_detection()


@api_bp.route('/api/threshold', methods=['POST'])
def set_threshold_simple():
    """POST /api/threshold — gateway relay."""
    return set_threshold()


@api_bp.route('/api/overlay_threshold', methods=['POST'])
def set_overlay_threshold_simple():
    """POST /api/overlay_threshold — gateway relay."""
    return set_overlay_threshold()


@api_bp.route('/api/models', methods=['GET'])
def list_models_simple():
    """GET /api/models — gateway relay."""
    result = list_models()
    data = json.loads(result.get_data(as_text=True))
    return _json(data.get("models", []) if isinstance(data, dict) else [])


@api_bp.route('/api/health', methods=['GET'])
def health_check_simple():
    """GET /api/health — gateway relay."""
    return health_check()


@api_bp.route('/api/classes', methods=['GET'])
def get_classes_simple():
    """GET /api/classes — gateway relay."""
    return get_classes()


@api_bp.route('/api/classes', methods=['POST'])
def upload_classes_simple():
    """POST /api/classes — gateway relay."""
    return upload_classes()
