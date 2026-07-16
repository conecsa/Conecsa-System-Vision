"""
Model settings service.

Persists per-model tuning — confidence/overlay thresholds and
camera configuration — to a sibling JSON file next to the model file
(e.g. weights.engine -> weights.settings.json), and applies them when a
model is activated.

This mirrors the per-model classes file (weights.txt) and per-model
detection areas (weights.areas.json): each model carries its own tuning,
restored automatically on selection and at startup.
"""
import errno
import json
import logging
import os
import tempfile
from threading import Lock
from typing import Optional

from ..config import Config

logger = logging.getLogger(__name__)


class ModelSettingsService:
    """Per-model thresholds + camera config, persisted as a sibling JSON file."""

    def __init__(self, config: Config, video_service=None) -> None:
        self._config = config
        self._video_service = video_service
        # Resolved on switch_model(); None means "no model scoped yet".
        self._settings_path: Optional[str] = None
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Model switching
    # ------------------------------------------------------------------

    def switch_model(self, settings_path: str) -> None:
        """Point at a model's settings file and apply it.

        If the file exists, its thresholds + camera config are loaded and
        applied. If it does not exist yet, the current in-memory settings are
        persisted to seed it, so the model immediately owns a snapshot that
        subsequent edits update.
        """
        with self._lock:
            self._settings_path = os.path.abspath(settings_path)
            path = self._settings_path

        if os.path.exists(path):
            self.load_and_apply()
        else:
            self.save()

    # ------------------------------------------------------------------
    # Load / apply
    # ------------------------------------------------------------------

    def load_and_apply(self) -> None:
        """Read the active model's settings file and apply it to live state."""
        with self._lock:
            path = self._settings_path
        if not path or not os.path.exists(path):
            return

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001 - best-effort restore
            logger.error("Failed to read model settings %s: %s", path, exc)
            return

        thresholds = data.get("thresholds", {}) or {}
        conf = thresholds.get("confidence")
        overlay = thresholds.get("overlay")
        if isinstance(conf, (int, float)) and 0.0 <= conf <= 1.0:
            self._config.CONFIDENCE_THRESHOLD = float(conf)
        if isinstance(overlay, (int, float)) and 0.0 <= overlay <= 1.0:
            self._config.OVERLAY_THRESHOLD = float(overlay)

        camera = data.get("camera")
        if camera and self._video_service is not None:
            # Best-effort: webcam server may not be reachable at boot; the
            # config is re-applied on the next selection/change regardless.
            self._video_service.apply_webcam_server_config(camera)

        stereo = data.get("stereo")
        if isinstance(stereo, dict) and self._video_service is not None:
            self._video_service.set_stereo_config(
                stereo.get("enabled"),
                stereo.get("alpha"),
                stereo.get("offset"),
                stereo.get("offset_y"),
            )

        logger.info("Applied per-model settings from %s", path)

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Snapshot the live thresholds + camera config to the model's file."""
        with self._lock:
            path = self._settings_path
        if not path:
            return

        payload = {
            "thresholds": {
                "confidence": self._config.CONFIDENCE_THRESHOLD,
                "overlay": self._config.OVERLAY_THRESHOLD,
            },
        }
        if self._video_service is not None:
            camera = self._video_service.get_current_camera_config()
            if camera:
                payload["camera"] = camera
            payload["stereo"] = self._video_service.get_stereo_config()

        tmp_path = None
        try:
            storage_dir = os.path.dirname(path)
            os.makedirs(storage_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w",
                dir=storage_dir,
                prefix=".model_settings_",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                tmp_path = f.name
            os.replace(tmp_path, path)
        except Exception as exc:  # noqa: BLE001 - best-effort persist
            logger.error("Failed to persist model settings to %s: %s", path, exc)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError as cleanup_exc:
                    if cleanup_exc.errno != errno.ENOENT:
                        logger.warning(
                            "Failed to remove temp model settings file %s: %s",
                            tmp_path,
                            cleanup_exc,
                        )
