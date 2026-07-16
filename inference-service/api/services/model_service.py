"""
Model service - Manages model loading and switching.
"""
import os
import logging
from typing import List, Tuple
from threading import Lock

from ..config import Config
from ..models.detection_models import ModelInfo
from ..runtime_management import RuntimeFactory

logger = logging.getLogger(__name__)

# Extensions that require async conversion before they can be used
_PT_EXTENSIONS = {'.pt'}
_ONNX_EXTENSIONS = {'.onnx'}


class ModelService:
    """Service for managing ML models."""

    # Filename (within the model directory) used to remember the last-selected
    # model across restarts. Referenced by api_server's TRT bootstrap too, so
    # it does not pre-load a different engine over the restored one.
    STATE_FILENAME = ".current_model"

    def __init__(self, config: Config, model_directory: str):
        """
        Initialize the model service.

        Args:
            config: Configuration instance
            model_directory: Directory containing models
        """
        self.config = config
        self.model_directory = model_directory
        self.current_model = "weights.engine"  # Default model name
        self.lock = Lock()
        self._detection_service = None  # Wired via attach_detection_service()
        self._area_service = None       # Wired via attach_area_service()
        self._settings_service = None   # Wired via attach_settings_service()
        self._conversion_service = None  # Wired via attach_conversion_service()
        # State file used to remember the last-selected model across restarts
        # so the app can boot back into the same model.
        self._state_file = os.path.join(model_directory, self.STATE_FILENAME)

        # Ensure model directory exists
        os.makedirs(model_directory, exist_ok=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def classes_file_for_model(model_path: str) -> str:
        """Return the per-model classes.txt file path (sibling of the model file).

        Example: /data/models/weights.engine -> /data/models/weights.txt
        """
        base, _ = os.path.splitext(model_path)
        return f"{base}.txt"

    @staticmethod
    def areas_file_for_model(model_path: str) -> str:
        """Return the per-model detection-areas file path (sibling of the model).

        Example: /data/models/weights.engine -> /data/models/weights.areas.json
        """
        base, _ = os.path.splitext(model_path)
        return f"{base}.areas.json"

    @staticmethod
    def settings_file_for_model(model_path: str) -> str:
        """Return the per-model settings file path (thresholds + camera config).

        Example: /data/models/weights.engine -> /data/models/weights.settings.json
        """
        base, _ = os.path.splitext(model_path)
        return f"{base}.settings.json"

    def attach_detection_service(self, detection_service) -> None:
        """Inject DetectionService for the activate_model lifecycle.

        Done post-construction to avoid a constructor-time circular dep
        with the Application container.
        """
        self._detection_service = detection_service

    def attach_area_service(self, area_service) -> None:
        """Inject DetectionAreaService so model selection switches the
        per-model detection-areas file."""
        self._area_service = area_service

    def attach_settings_service(self, settings_service) -> None:
        """Inject ModelSettingsService so model selection switches the
        per-model thresholds + camera settings file."""
        self._settings_service = settings_service

    def attach_conversion_service(self, conversion_service) -> None:
        """Inject ConversionService so process_upload can enqueue the async
        .pt/.onnx → .engine conversion jobs."""
        self._conversion_service = conversion_service

    # ------------------------------------------------------------------
    # Last-selected-model persistence
    # ------------------------------------------------------------------

    def _persist_current_model(self, model_name: str) -> None:
        """Write the last-selected model name to disk (best-effort)."""
        try:
            with open(self._state_file, "w") as f:
                f.write(model_name.strip())
        except OSError as ex:
            logger.warning(f"Could not persist current model '{model_name}': {ex}")

    def load_persisted_current_model(self) -> str:
        """Read the last-selected model name from disk, or '' if none."""
        try:
            with open(self._state_file, "r") as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""
        except OSError as ex:
            logger.warning(f"Could not read persisted current model: {ex}")
            return ""

    def list_models(self) -> List[ModelInfo]:
        """
        List all available models.

        Returns:
            List of ModelInfo objects
        """
        models: List[ModelInfo] = []

        if not os.path.exists(self.model_directory):
            logger.warning(f"Model directory does not exist: {self.model_directory}")
            return models

        allowed_extensions = ('.engine', '.plan', '.pt', '.onnx')

        for filename in os.listdir(self.model_directory):
            if filename.endswith(allowed_extensions):
                try:
                    file_path = os.path.join(self.model_directory, filename)
                    models.append(ModelInfo(
                        name=filename,
                        path=file_path,
                        size=os.path.getsize(file_path),
                        modified=os.path.getmtime(file_path),
                        is_active=(filename == self.current_model)
                    ))
                except Exception as ex:
                    logger.warning(f"Error reading model file {filename}: {ex}")
                    continue

        return models

    def model_file_path(self, model_name: str) -> str:
        """
        Resolve a model name to its file path for download.

        Returns "" when the name is not a plain model filename (path
        traversal), has a disallowed extension, or the file is missing.
        """
        allowed_extensions = ('.engine', '.plan', '.pt', '.onnx')
        if (not model_name
                or any(c in model_name for c in ('"', '\r', '\n'))
                or os.path.basename(model_name) != model_name
                or not model_name.endswith(allowed_extensions)):
            return ""
        path = os.path.join(self.model_directory, model_name)
        return path if os.path.isfile(path) else ""

    def save_model(self, filename: str, file_data) -> Tuple[bool, str, str]:
        """
        Save an uploaded model file.

        Args:
            filename: Name of the model file
            file_data: File object with model data

        Returns:
            Tuple of (success, model_path, error_message)
        """
        allowed_extensions = ['.engine', '.plan', '.pt', '.onnx']
        file_ext = os.path.splitext(filename)[1]

        if file_ext not in allowed_extensions:
            return False, "", f"Invalid file type. Allowed: {allowed_extensions}"

        try:
            model_path = os.path.join(self.model_directory, filename)
            file_data.save(model_path)
            logger.info(f"Model saved successfully: {model_path}")
            return True, model_path, ""
        except Exception as ex:
            logger.error(f"Error saving model: {ex}")
            return False, "", str(ex)

    def process_upload(self, filename: str, file_data, imgsz: int = 640) -> Tuple[dict, int]:
        """Full upload lifecycle — owns the business logic so both the REST
        controller and the gRPC servicer are thin adapters over it.

        Saves the uploaded file, then branches on extension:
          - .pt   → enqueue async .pt → .onnx → .engine conversion (202)
          - .onnx → enqueue async .onnx → .engine conversion (202)
          - other → activate immediately (load into the live detector) (200)

        Args:
            filename: Uploaded file name (drives the extension branch).
            file_data: File-like object exposing ``.save(path)`` (Flask
                FileStorage over HTTP, or a bytes adapter over gRPC).
            imgsz: Image size for .pt conversion (ignored otherwise).

        Returns:
            (body, http_status) — body is the JSON-serializable response the
            gateway relays verbatim; http_status is the intended HTTP status
            (202 converting / 200 loaded / 4xx-5xx error).
        """
        if not filename:
            return {"error": "No file selected"}, 400

        if self._conversion_service is None:
            raise RuntimeError(
                "ModelService.process_upload requires attach_conversion_service() "
                "to be called during application wiring."
            )

        logger.info(f"Uploading model: {filename}")
        success, model_path, error_message = self.save_model(filename, file_data)
        if not success:
            logger.error(error_message)
            return {"error": error_message}, 500

        file_ext = os.path.splitext(filename)[1].lower()

        # ── .pt model: start async .pt → .onnx → .engine conversion ──────────
        if file_ext in _PT_EXTENSIONS:
            job = self._conversion_service.start_pt_conversion(
                pt_path=model_path,
                original_filename=filename,
                model_directory=self.model_directory,
                imgsz=imgsz,
            )
            logger.info(f"Async conversion job {job.job_id} started for {filename}")
            return {
                "status": "converting",
                "message": (
                    f"'{filename}' received. Converting to TensorRT engine "
                    "in the background. Poll the conversion status endpoint for progress."
                ),
                "job_id": job.job_id,
                "filename": filename,
            }, 202

        # ── .onnx model: start async .onnx → .engine conversion ──────────────
        if file_ext in _ONNX_EXTENSIONS:
            job = self._conversion_service.start_onnx_conversion(
                onnx_path=model_path,
                original_filename=filename,
                model_directory=self.model_directory,
            )
            logger.info(f"Async ONNX conversion job {job.job_id} started for {filename}")
            return {
                "status": "converting",
                "message": (
                    f"'{filename}' received. Building TensorRT engine "
                    "in the background. Poll the conversion status endpoint for progress."
                ),
                "job_id": job.job_id,
                "filename": filename,
            }, 202

        # ── Other formats: load immediately ──────────────────────────────────
        success, result, _was_running = self.activate_model(filename)
        if not success:
            logger.error(result)
            return {"error": result}, 500

        logger.info(f"Model {filename} uploaded and loaded successfully")
        return {
            "status": "success",
            "message": "Model uploaded and loaded successfully",
            "model": filename,
            "path": result,
        }, 200

    def select_model(self, model_name: str) -> Tuple[bool, str]:
        """
        Select a model to use.

        Args:
            model_name: Name of the model file

        Returns:
            Tuple of (success, model_path or error_message)
        """
        model_path = os.path.join(self.model_directory, model_name)

        if not os.path.exists(model_path):
            return False, f"Model '{model_name}' not found"

        file_ext = os.path.splitext(model_name)[1].lower()
        if file_ext not in ('.engine', '.plan', '.pt', '.onnx'):
            return (
                False,
                "Deprecated model format requested. Only .engine, .plan, .pt and .onnx are supported.",
            )

        if not RuntimeFactory.is_supported_model(model_path):
            return False, f"No supported runtime available for model '{model_name}'"

        classes_path = self.classes_file_for_model(model_path)
        areas_path = self.areas_file_for_model(model_path)
        settings_path = self.settings_file_for_model(model_path)

        with self.lock:
            self.current_model = model_name
            self.config.MODEL_PATH = model_path
            self.config.CLASSES_FILE_PATH = classes_path

        # Switch all per-model scoped state to this model's sibling files.
        # Areas and settings are switched before the detector is (re)initialized
        # by activate_model, so the new model boots with its own tuning.
        if self._area_service is not None:
            self._area_service.switch_storage(areas_path)
        if self._settings_service is not None:
            self._settings_service.switch_model(settings_path)

        self._persist_current_model(model_name)

        logger.info(
            f"Model selected: {model_name} "
            f"(classes: {classes_path}, areas: {areas_path}, settings: {settings_path})"
        )
        return True, model_path

    def activate_model(self, model_name: str) -> Tuple[bool, str, bool]:
        """
        Full lifecycle to switch the active model in a live system.

        Stops the detection loop (if running), selects the new model and its
        per-model classes file, re-initializes the detector, and restarts the
        loop if it had been running.

        Args:
            model_name: Name of the model file to activate.

        Returns:
            A ``(success, model_path_or_error, was_running)`` tuple. On failure
            (``success=False``) ``model_path_or_error`` holds the error message
            and the detection loop is left stopped (the caller decides what to
            do). On success ``model_path_or_error`` is the resolved model path
            and ``was_running`` says whether the loop was running beforehand
            (and has now been restarted).

        Raises:
            RuntimeError: if attach_detection_service() was not called.
        """
        if self._detection_service is None:
            raise RuntimeError(
                "ModelService.activate_model requires attach_detection_service() "
                "to be called during application wiring."
            )

        was_running = self._detection_service.stop()

        success, result = self.select_model(model_name)
        if not success:
            return False, result, was_running

        try:
            self._detection_service.initialize()
        except Exception as ex:  # noqa: BLE001 - surfaced to caller
            logger.error(f"Failed to initialize detection after selecting '{model_name}': {ex}")
            return False, f"Failed to load model: {ex}", was_running

        if was_running:
            self._detection_service.start()

        return True, result, was_running

    def delete_model(self, model_name: str) -> Tuple[bool, str]:
        """
        Delete a model file.

        Args:
            model_name: Name of the model file

        Returns:
            Tuple of (success, error_message)
        """
        if model_name == self.current_model:
            return False, "Cannot delete the currently active model"

        model_path = os.path.join(self.model_directory, model_name)

        if not os.path.exists(model_path):
            return False, f"Model '{model_name}' not found"

        try:
            os.remove(model_path)
            logger.info(f"Model deleted: {model_name}")
            return True, ""
        except Exception as ex:
            logger.error(f"Error deleting model: {ex}")
            return False, str(ex)

