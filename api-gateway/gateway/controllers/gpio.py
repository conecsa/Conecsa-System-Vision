"""GPIO controller: trigger-output enable/disable and direct pin control via
the os hardware agent."""
import logging

from flask import request

from .. import hardware
from ..helpers import _json, _publish_if_success, _response_json
from . import api_bp

logger = logging.getLogger(__name__)


@api_bp.route('/api/v1/gpio/status', methods=['GET'])
def gpio_status():
    """GET /api/v1/gpio/status — gateway relay."""
    try:
        return _json(hardware.get_gpio_status())
    except Exception as exc:  # noqa: BLE001
        logger.error("Error getting GPIO status: %s", exc)
        return _json({"error": str(exc)}, 500)


@api_bp.route('/api/v1/gpio/trigger', methods=['POST'])
def gpio_set_trigger():
    """POST /api/v1/gpio/trigger — gateway relay."""
    body = request.get_json(silent=True) or {}
    if "enabled" not in body:
        return _json({"error": "'enabled' field is required"}, 400)
    enabled = bool(body["enabled"])
    try:
        hardware.set_gpio_enabled(enabled)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error setting GPIO trigger: %s", exc)
        return _json({"error": str(exc)}, 500)
    resp = _json({"success": True, "gpio_enabled": enabled,
                  "message": f"GPIO trigger {'enabled' if enabled else 'disabled'}"})
    return _publish_if_success(resp, "gpio_changed", ["gpio"], data=_response_json(resp))


@api_bp.route('/api/v1/gpio/pin', methods=['POST'])
def gpio_set_pin():
    """POST /api/v1/gpio/pin — drive a single output pin HIGH/LOW (gateway relay)."""
    body = request.get_json(silent=True) or {}
    if "pin" not in body or "level" not in body:
        return _json({"error": "'pin' and 'level' fields are required"}, 400)
    try:
        pin = int(body["pin"])
    except (TypeError, ValueError):
        return _json({"error": "'pin' must be an integer"}, 400)
    if pin not in hardware._OUTPUT_PINS:
        return _json({"error": f"pin {pin} is not a controllable output pin"}, 400)

    raw_level = body["level"]
    if not isinstance(raw_level, bool):
        return _json({"error": "'level' must be a boolean"}, 400)
    level = raw_level
    try:
        hardware.set_gpio_pin(pin, level)
    except Exception as exc:  # noqa: BLE001
        logger.error("Error setting GPIO pin %s: %s", pin, exc)
        return _json({"error": str(exc)}, 500)
    resp = _json({"success": True, "pin": pin, "level": level,
                  "message": f"Pin {pin} set {'HIGH' if level else 'LOW'}"})
    return _publish_if_success(resp, "gpio_changed", ["gpio"], data=_response_json(resp))
