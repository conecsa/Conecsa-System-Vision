"""
Config service - reads and applies the app capture/inference configuration.

Holds the business logic that used to live in ConfigController so both the REST
controller and the gRPC servicer stay thin adapters that delegate here.
"""
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ConfigService:
    """Owns get/update of the capture device + framerate + confidence threshold,
    proxying camera changes to the webcam-server and persisting per-model."""

    def __init__(self, config, video_service=None, settings_service=None):
        self._config = config
        self._video = video_service
        self._settings = settings_service

    def get_config(self) -> Dict:
        """Return the current configuration (device, resolution, thresholds, …)."""
        c = self._config
        return {
            "capture_device": c.CAPTURE_DEVICE,
            "capture_resolution": [c.CAPTURE_RESOLUTION_X, c.CAPTURE_RESOLUTION_Y],
            "capture_framerate": c.CAPTURE_FRAMERATE,
            "model_path": c.MODEL_PATH,
            "confidence_threshold": c.CONFIDENCE_THRESHOLD,
        }

    def update_config(self, data: Dict) -> Tuple[bool, str]:
        """Apply a partial config patch. Returns ``(ok, message)``."""
        if not data:
            return False, "No data provided"
        c = self._config
        try:
            if "capture_device" in data:
                c.CAPTURE_DEVICE = data["capture_device"]
                if self._video is not None:
                    try:
                        idx = int(str(data["capture_device"]).replace("/dev/video", ""))
                        self._video.apply_webcam_server_config({"camera_index": idx})
                    except ValueError:
                        pass
            if "capture_framerate" in data:
                c.CAPTURE_FRAMERATE = int(data["capture_framerate"])
                if self._video is not None:
                    self._video.apply_webcam_server_config({"framerate": c.CAPTURE_FRAMERATE})
            if "confidence_threshold" in data:
                c.CONFIDENCE_THRESHOLD = float(data["confidence_threshold"])
            if self._settings is not None:
                self._settings.save()
            return True, "Configuration updated"
        except Exception as ex:  # noqa: BLE001
            logger.error("Error updating config: %s", ex)
            return False, str(ex)
