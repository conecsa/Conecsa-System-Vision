"""
Composition root for the headless inference-service.

Wires the concrete in-process services + the decode∥infer∥encode pipeline.
`main.py` constructs ``Application`` and the gRPC servicers
(``api/inference_grpc.py``) drive these services directly — there is no HTTP /
controller layer (the api-gateway owns the REST/SSE/MJPEG surface).
"""
import logging
import os
import threading

from api.config import Config
from api.services import (
    DetectionBufferService, DetectionService, ModelService, VideoService,
    StatsService, ConversionService,
    GPIOService, DetectionAreaService, ModelSettingsService,
    ConsumerService, FrameCodecService, ProcessingPipelineService, EventService,
    ConfigService,
)
from api.views import OverlayRenderer

logger = logging.getLogger(__name__)

# How long the boot auto-start waits for the webcam-server to report a streaming
# camera before giving up and leaving detection stopped.
CAMERA_BOOT_TIMEOUT = float(os.environ.get("CAMERA_BOOT_TIMEOUT", 15))


def get_model_directory():
    """Resolve model directory for container and local development.

    Priority:
    1) Explicit MODELS_DIR env var
    2) /data/models when writable (container volume)
    3) repo-local uploaded_models directory for local runs
    """
    explicit = os.environ.get("MODELS_DIR")
    if explicit:
        return explicit

    container_models_dir = "/data/models"
    if os.path.isdir(container_models_dir) and os.access(container_models_dir, os.W_OK | os.X_OK):
        return container_models_dir

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    local_models_dir = os.path.join(repo_root, "uploaded_models")
    os.makedirs(local_models_dir, exist_ok=True)
    return local_models_dir


def get_detections_directory():
    """Resolve the offline detection-buffer directory.

    Priority (mirrors get_model_directory):
    1) Explicit DETECTIONS_DIR env var
    2) /data/detections when writable (container volume)
    3) repo-local buffered_detections directory for local runs
    """
    explicit = os.environ.get("DETECTIONS_DIR")
    if explicit:
        return explicit

    container_dir = "/data/detections"
    if os.path.isdir(container_dir) and os.access(container_dir, os.W_OK | os.X_OK):
        return container_dir

    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    local_dir = os.path.join(repo_root, "buffered_detections")
    os.makedirs(local_dir, exist_ok=True)
    return local_dir


# Initialize application components
def _bootstrap_tensorrt_worker() -> None:
    """Start the TRT worker process eagerly in the background.

    The worker initializes ``pycuda.autoinit`` (and therefore the CUDA
    context) the first time it processes a command, so engine builds work
    even when no .engine file exists yet.  Starting it here avoids the
    30-second cold-start delay that would otherwise be added to the first
    upload request.
    """
    def _run() -> None:
        """Warm-up thread body: let startup settle, then start the worker."""
        # Small delay so startup (model restore + gRPC bind) settles first
        threading.Event().wait(3.0)
        try:
            from api.runtime_management.worker_client import get_worker_client
            client = get_worker_client()
            # ensure_connected() starts the subprocess and waits for it to
            # accept connections — no model loading needed.
            client.ensure_connected()
            logger.info("TRT bootstrap: worker process started and ready.")

            models_dir = get_model_directory()

            # If a model is already active — restored by initialize() or
            # selected by the user during the warm-up window — its engine is
            # already loaded in the worker. Pre-loading a *different* engine
            # here would clobber it (the detector would silently run the wrong
            # model). So only warm the context with engines[0] when there is no
            # persisted/active model.
            state_file = os.path.join(models_dir, ModelService.STATE_FILENAME)
            try:
                with open(state_file) as f:
                    persisted_name = f.read().strip()
            except OSError:
                persisted_name = ""
            has_active_model = bool(persisted_name) and os.path.exists(
                os.path.join(models_dir, persisted_name)
            )
            if has_active_model:
                logger.info(
                    "TRT bootstrap: active model '%s' already loaded by initialize(); "
                    "skipping warm-up pre-load.",
                    persisted_name,
                )
            elif os.path.isdir(models_dir):
                # No active model — warm the CUDA context with any available
                # engine so the first conversion/build is fast.
                engines = sorted(
                    f for f in os.listdir(models_dir)
                    if f.endswith((".engine", ".plan"))
                )
                if engines:
                    engine_path = os.path.join(models_dir, engines[0])
                    logger.info("TRT bootstrap: pre-loading '%s' for warm CUDA context.", engine_path)
                    client.load_model(engine_path)
                    logger.info("TRT bootstrap: CUDA context warm — fast-path active.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("TRT bootstrap failed (non-fatal): %s", exc)

    threading.Thread(target=_run, daemon=True, name="trt-bootstrap").start()


class Application:
    """Application container for dependency injection."""

    def __init__(self):
        model_directory = get_model_directory()
        os.environ.setdefault("MODELS_DIR", model_directory)

        # Configuration
        self.config = Config()

        # Services
        # Transport + image codec are independent services; VideoService is the
        # camera-config facade over them.
        self.consumer_service = ConsumerService(shm_name=self.config.SHM_NAME)
        self.codec_service = FrameCodecService()
        self.video_service = VideoService(self.consumer_service, self.codec_service)

        # Per-model thresholds + camera config (sibling weights.settings.json),
        # switched on model selection and restored at startup.
        self.model_settings_service = ModelSettingsService(self.config, self.video_service)

        # Detection areas are scoped per-model (sibling weights.areas.json).
        # Seed with the default model's file; switched on selection.
        self.detection_area_service = DetectionAreaService(
            storage_path=ModelService.areas_file_for_model(self.config.MODEL_PATH)
        )
        # Store-and-forward buffer: records detection changes on disk while the
        # hub is not polling, drained by the hub on reconnect (ListBacklog/Ack).
        self.detection_buffer = DetectionBufferService(
            db_path=os.path.join(get_detections_directory(), "buffer.db"),
            max_records=self.config.DETECTION_BUFFER_MAX_RECORDS,
            max_bytes=self.config.DETECTION_BUFFER_MAX_BYTES,
            offline_threshold_s=self.config.HUB_OFFLINE_THRESHOLD_SEC,
        )
        self.detection_service = DetectionService(
            self.config,
            area_service=self.detection_area_service,
            video_service=self.video_service,
            buffer_service=self.detection_buffer,
        )
        self.model_service = ModelService(self.config, model_directory)
        self.model_service.attach_detection_service(self.detection_service)
        self.model_service.attach_area_service(self.detection_area_service)
        self.model_service.attach_settings_service(self.model_settings_service)
        self.stats_service = StatsService()
        self.event_service = EventService()
        self.conversion_service = ConversionService(self.event_service)
        self.model_service.attach_conversion_service(self.conversion_service)
        # Fan stats out over the unified app-event SSE stream so web clients
        # need a single connection (events + stats) instead of two.
        self.stats_service.set_update_listener(self.event_service.publish_stats)

        # App capture/inference config (get/update), proxying camera changes and
        # persisting per-model — keeps ConfigController/gRPC thin.
        self.config_service = ConfigService(
            self.config, self.video_service, self.model_settings_service
        )

        # GPIO service (client to the os hardware agent: SHM hot path + gRPC)
        self.gpio_service = GPIOService()

        # Shared decode∥infer∥encode pipeline — the single producer of the
        # processed stream (all HTTP clients fan out from it).
        self.pipeline_service = ProcessingPipelineService(
            self.consumer_service,
            self.codec_service,
            self.detection_service,
            self.stats_service,
            self.gpio_service,
            OverlayRenderer(),
            self.video_service,
        )

        # No HTTP controllers — inference is headless. The gRPC servicers
        # (api/inference_grpc.py) drive the services above directly; the
        # api-gateway owns the REST/SSE/MJPEG surface.

        # Pre-warm TRT worker in background so CUDA context is ready before
        # the first .pt upload arrives
        _bootstrap_tensorrt_worker()

    def initialize(self):
        """Initialize the application.

        Restores the last-selected model (persisted by ModelService) and
        auto-starts detection so the system boots back into the same state.
        Falls back to a plain detector init if no persisted model is usable.
        """
        logger.info("Initializing application...")

        persisted = self.model_service.load_persisted_current_model()
        if persisted:
            logger.info(f"Restoring last-selected model: {persisted}")
            success, result, _was_running = self.model_service.activate_model(persisted)
            if success:
                # The webcam-server opens the device concurrently with this boot,
                # so give it a grace period before deciding there is no camera.
                # Without one, detection stays stopped and the UI says why.
                if not self.video_service.wait_for_camera(timeout=CAMERA_BOOT_TIMEOUT):
                    logger.warning("Detection not auto-started: no camera connected")
                else:
                    try:
                        self.detection_service.start()
                        logger.info(f"Auto-started detection with model: {persisted}")
                    except RuntimeError as ex:
                        logger.warning(f"Detection not auto-started: {ex}")
                logger.info("Application initialized successfully")
                return
            logger.warning(f"Could not restore persisted model '{persisted}': {result}")

        # No persisted state, or restore failed — scope per-model settings to
        # the default model so areas/thresholds/camera edits still persist,
        # then try a plain init so the service is at least reachable;
        # downstream calls will surface any missing-model errors.
        self.model_settings_service.switch_model(
            ModelService.settings_file_for_model(self.config.MODEL_PATH)
        )
        try:
            self.detection_service.initialize()
        except FileNotFoundError as ex:
            logger.warning(f"No model loaded at startup: {ex}")
        logger.info("Application initialized successfully")
