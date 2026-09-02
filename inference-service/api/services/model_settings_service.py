"""
Model settings service.

Persists per-model tuning — confidence/overlay thresholds and
camera configuration — to a sibling JSON file next to the model file
(e.g. weights.engine -> weights.settings.json), and applies them when a
model is activated.

This mirrors the per-model classes file (weights.txt) and per-model
detection areas (weights.areas.json): each model carries its own tuning,
restored automatically on selection and at startup.

The file may also carry an informational ``"imgsz"`` (int) written by the
conversion job when a ``.pt`` is exported (640 or 1280). It is never applied to
anything — the engine dictates its own input size — but it survives every
``save()`` so the UI/logs can tell the builds apart. Files without the key load
unchanged.

The conversion job also records ``"training": {"geometry": ...}`` when the
uploader declared how the weights were trained (``"frames"``, ``"tiles:auto"``
or ``"tiles:<px>"``; the training-service always does). A model only performs
at the scale it was trained at, so ``switch_model`` compares that geometry with
the live ``TILING_MODE``/``TILING_TILE`` and logs a warning on a mismatch —
a whole-frame model under grid tiling, or a tile model with tiling off. The
geometry is never applied either; an unknown geometry is silent.
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

GEOMETRY_FRAMES = "frames"
GEOMETRY_TILES_AUTO = "tiles:auto"


def parse_train_geometry(value) -> Optional[str]:
    """A well-formed training geometry string, or ``None`` for anything else."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text in (GEOMETRY_FRAMES, GEOMETRY_TILES_AUTO):
        return text
    pixels = text[len("tiles:"):] if text.startswith("tiles:") else ""
    if pixels.isdigit() and int(pixels) > 0:
        return f"tiles:{int(pixels)}"
    return None


def geometry_mismatch(train_geometry: Optional[str], tiling_mode: str,
                      tiling_tile: Optional[int]) -> Optional[str]:
    """Why ``train_geometry`` disagrees with the live tiling knobs, or ``None``.

    ``tiling_tile`` is ``None`` for the ``auto`` tile (the frame's short
    side), which is what ``tiles:auto`` models were trained with.
    """
    geometry = parse_train_geometry(train_geometry)
    if geometry is None:
        return None
    if geometry == GEOMETRY_FRAMES:
        if tiling_mode == "grid":
            return ("trained on whole frames but TILING_MODE=grid slices every frame "
                    "into tiles the model has not seen at that scale; set TILING_MODE=off "
                    "or retrain it with TRAIN_TILE=auto")
        return None
    trained = geometry.split(":", 1)[1]
    if tiling_mode != "grid":
        return (f"trained on {trained} tiles but TILING_MODE=off runs the whole "
                "letterboxed frame; set TILING_MODE=grid")
    live = "auto" if tiling_tile is None else str(tiling_tile)
    if live != trained:
        return (f"trained on {trained} tiles but TILING_TILE={live}; align TILING_TILE "
                "with the TRAIN_TILE the model was trained with")
    return None


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
            data = self.load_and_apply()
            self._warn_on_geometry_mismatch(path, data)
            # A sidecar seeded by the conversion job holds only "imgsz" and
            # the training geometry; it still needs the threshold snapshot a
            # brand-new model would have got. A corrupt file (None) is left
            # alone, as before.
            if data is None or "thresholds" in data:
                return
        self.save()

    @staticmethod
    def _warn_on_geometry_mismatch(path: str, data: Optional[dict]) -> None:
        """Log when the model's recorded training geometry disagrees with TILING_*."""
        # Lazy: model_manager pulls in cv2 and the runtime registry, which the
        # settings sidecar does not otherwise need.
        from ..model_manager import tiling_mode_from_env, tiling_tile_from_env

        reason = geometry_mismatch(
            ModelSettingsService.training_geometry_of(data),
            tiling_mode_from_env(), tiling_tile_from_env())
        if reason:
            logger.warning("Model %s: %s", os.path.basename(path), reason)

    @staticmethod
    def training_geometry_of(data: Optional[dict]) -> Optional[str]:
        """The ``training.geometry`` value of a parsed settings payload, if well-formed."""
        training = (data or {}).get("training")
        if not isinstance(training, dict):
            return None
        return parse_train_geometry(training.get("geometry"))

    @classmethod
    def training_geometry(cls, settings_path: str) -> Optional[str]:
        """Read a model's recorded training geometry without activating it."""
        path = os.path.abspath(settings_path)
        if not os.path.exists(path):
            return None
        return cls.training_geometry_of(cls._read_payload(path))

    # ------------------------------------------------------------------
    # Load / apply
    # ------------------------------------------------------------------

    def load_and_apply(self) -> Optional[dict]:
        """Read the active model's settings file and apply it to live state.

        Returns the parsed payload, or ``None`` when there is no file or it
        could not be read.
        """
        with self._lock:
            path = self._settings_path
        if not path or not os.path.exists(path):
            return None

        data = self._read_payload(path)
        if data is None:
            return None

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
        return data

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Snapshot the live thresholds + camera config to the model's file.

        The informational ``imgsz`` and ``training`` already in the file (if
        any) are carried over so a threshold edit never erases them.
        """
        with self._lock:
            path = self._settings_path
        if not path:
            return

        payload: dict = {
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

        existing = self._read_payload(path) if os.path.exists(path) else None
        imgsz = (existing or {}).get("imgsz")
        if isinstance(imgsz, int) and not isinstance(imgsz, bool):
            payload["imgsz"] = imgsz
        geometry = self.training_geometry_of(existing)
        if geometry is not None:
            payload["training"] = {"geometry": geometry}

        self._write_payload(path, payload)

    @classmethod
    def record_training(cls, settings_path: str, imgsz: int,
                        train_geometry: Optional[str] = None) -> None:
        """Store the export image size and training geometry of a freshly converted model.

        Called by the conversion job when the engine is written, before the
        model is ever activated: merges ``"imgsz"`` (and ``"training"`` when
        the geometry is known and well-formed) into an existing settings file
        or creates one holding just those keys (``switch_model`` completes it
        with the threshold snapshot on first activation). Best-effort, like
        ``save``.
        """
        path = os.path.abspath(settings_path)
        payload = (cls._read_payload(path) if os.path.exists(path) else None) or {}
        payload["imgsz"] = int(imgsz)
        geometry = parse_train_geometry(train_geometry)
        if geometry is not None:
            payload["training"] = {"geometry": geometry}
        cls._write_payload(path, payload)

    @classmethod
    def record_imgsz(cls, settings_path: str, imgsz: int) -> None:
        """``record_training`` without a geometry (kept for callers that only know the size)."""
        cls.record_training(settings_path, imgsz)

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_payload(path: str) -> Optional[dict]:
        """Parse a settings file; ``None`` (logged) when unreadable or not a JSON object."""
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as exc:  # noqa: BLE001 - best-effort restore
            logger.error("Failed to read model settings %s: %s", path, exc)
            return None
        if not isinstance(data, dict):
            logger.error("Model settings %s is not a JSON object", path)
            return None
        return data

    @staticmethod
    def _write_payload(path: str, payload: dict) -> None:
        """Atomically write ``payload`` as JSON (temp file + ``os.replace``)."""
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
