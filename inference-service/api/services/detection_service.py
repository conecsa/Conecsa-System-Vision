"""
Detection service - Manages detection operations.
"""
import logging
from threading import Lock
from typing import Optional, List

# noinspection PyPackageRequirements
import numpy as np # Package is included on os build.

from ..model_manager import ModelManager
from ..yolo_detector import YOLODetector
from ..config import Config
from ..utils import load_class_labels
from ..models.detection_models import DetectionResult
from .detection_area_service import DetectionAreaService

logger = logging.getLogger(__name__)


def normalized_bbox(bbox, width: int, height: int) -> List[float]:
    """Pixel corners (x1, y1, x2, y2) → normalized [x1, y1, x2, y2] in 0..1."""
    x1, y1, x2, y2 = bbox
    def _clamp(v: float) -> float:
        return min(1.0, max(0.0, v))
    return [
        round(_clamp(x1 / width), 4),
        round(_clamp(y1 / height), 4),
        round(_clamp(x2 / width), 4),
        round(_clamp(y2 / height), 4),
    ]


def _encode_frame_b64(image: np.ndarray) -> Optional[str]:
    """JPEG-encode a frame (quality 80) and return it base64-encoded."""
    import base64
    # noinspection PyPackageRequirements
    import cv2  # Package is included on os build
    ok, buf = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return None
    # buf.data is a zero-copy memoryview onto the encoded JPEG; b64encode reads it
    # directly, avoiding the extra bytes copy tobytes() would make. memoryview(buf)
    # would also work but trips older numpy stubs (ndarray predates PEP 688's Buffer).
    return base64.b64encode(buf.data).decode('ascii')


class DetectionService:
    """Service for managing object detection operations."""

    def __init__(
        self,
        config: Config,
        area_service: Optional[DetectionAreaService] = None,
        video_service=None,
        buffer_service=None,
    ):
        """
        Initialize the detection service.

        Args:
            config: Configuration instance
            area_service: Optional detection-area repository. When provided,
                its current snapshot is pushed to the YOLO detector before
                each frame so the detector can spatially filter and overlay.
            video_service: Optional VideoService, used to refuse starting
                detection while no camera is streaming (the webcam-server
                publishes no frames at all in that case).
            buffer_service: Optional DetectionBufferService that persists
                on-change results while the hub is not polling (offline
                store-and-forward); observed from finish().
        """
        self.config: Config = config
        self.area_service: Optional[DetectionAreaService] = area_service
        self.video_service = video_service
        self.buffer_service = buffer_service
        self.model_manager: Optional[ModelManager] = None
        self.yolo_detector: Optional[YOLODetector] = None
        self.class_labels: List[str] = []
        self.is_running: bool = False
        self.lock: Lock = Lock()
        self.trigger_enabled: bool = True
        self._detection_count: int = 0
        self._count_lock: Lock = Lock()
        self.last_detection_result: Optional[DetectionResult] = None

    def initialize(self) -> bool:
        """
        Initialize the detection model and components.

        Returns:
            bool: True if initialization successful, False otherwise
        """
        try:
            # Check if model file exists
            import os
            if not os.path.exists(self.config.MODEL_PATH):
                logger.error(f"Model file not found: {self.config.MODEL_PATH}")
                raise FileNotFoundError(
                    f"No model loaded. Please upload and select a model before starting detection."
                )
            
            logger.info("Initializing model manager...")
            self.model_manager = ModelManager(self.config)

            logger.info("Loading class labels...")
            self.class_labels = load_class_labels(self.config)

            logger.info("Initializing YOLO detector...")
            self.yolo_detector = YOLODetector(self.class_labels, self.config)

            logger.info("Detection service initialized successfully")
            return True
        except FileNotFoundError as ex:
            logger.error(f"Model file error: {ex}")
            raise
        except Exception as ex:
            logger.error(f"Error initializing detection service: {ex}")
            raise RuntimeError(f"Failed to initialize detection service: {str(ex)}")

    def start(self) -> bool:
        """
        Start detection processing.

        Returns:
            bool: True if started successfully, False if already running

        Raises:
            RuntimeError: if no camera is streaming.
        """
        with self.lock:
            if self.is_running:
                return False

            if self.video_service and not self.video_service.camera_connected():
                raise RuntimeError(
                    "No camera connected. Connect a camera before starting detection."
                )

            # Initialize if not already done
            if not self.model_manager:
                self.initialize()  # This will raise an exception if it fails

            self.is_running = True
            logger.info("Detection started")
        return True

    def stop(self) -> bool:
        """
        Stop detection processing.

        Returns:
            bool: True if stopped successfully, False if not running
        """
        with self.lock:
            if not self.is_running:
                return False

            self.is_running = False
            logger.info("Detection stopped")
        return True

    # ------------------------------------------------------------------
    # Pipeline stages — split into prepare/infer/finish so the processing
    # pipeline can run them on separate threads (decode/preprocess ∥
    # inference ∥ postprocess overlap).
    # ------------------------------------------------------------------

    def prepare(self, frame: np.ndarray):
        """Stage A: snapshot detection areas + preprocess.

        Returns ``(input_data, meta)`` where ``meta`` is the
        ``(scale, border_top, actual_input_size)`` tuple needed by ``finish``,
        or ``None`` if detection is not ready.
        """
        if not self.is_running or not self.model_manager or not self.yolo_detector:
            return None

        # Snapshot the current detection areas onto the detector so they apply
        # to this frame's filtering + overlay.
        if self.area_service is not None:
            self.yolo_detector.set_areas(self.area_service.list())

        input_data, scale, border_top, actual_input_size = self.model_manager.preprocess_image(frame)
        return input_data, (scale, border_top, actual_input_size)

    def infer(self, input_data):
        """Stage B: run inference. Returns ``(output_data, inference_time)``.

        Only reachable once ``prepare`` returned a non-None result, which already
        implies a model manager; the guard exists so a stopped detector fails loudly
        instead of raising AttributeError on None.
        """
        model_manager = self.model_manager
        if model_manager is None:
            raise RuntimeError("Detection is not running: no model manager")
        return model_manager.run_inference(input_data)

    def finish(self, output_data, frame: np.ndarray, meta, inference_time: float = 0.0) -> Optional[DetectionResult]:
        """Stage C: postprocess detections + draw overlay. Returns DetectionResult."""
        if not self.yolo_detector:
            return None
        scale, border_top, actual_input_size = meta
        processed_frame, num_detections, detection_objects = self.yolo_detector.process_detections(
            output_data, frame, scale=scale, border_top=border_top, actual_input_size=actual_input_size
        )
        result = DetectionResult(
            detections=detection_objects,
            processed_image=processed_frame,
            inference_time=inference_time,
            num_detections=num_detections,
            raw_image=frame,
        )
        self.last_detection_result = result
        if self.buffer_service is not None:
            # Offline store-and-forward: never let the buffer take down the
            # pipeline. Runs on the single pipeline-finish thread.
            try:
                self.buffer_service.observe(
                    self._detection_dicts(result),
                    result.num_detections,
                    self._model_name(),
                    result.raw_image,
                    result.processed_image,
                )
            except Exception:
                logger.exception("detection buffer observe failed")
        return result

    def set_confidence_threshold(self, threshold: float) -> bool:
        """
        Set the confidence threshold for detections.

        Args:
            threshold: Confidence threshold (0.0 to 1.0)

        Returns:
            bool: True if set successfully
        """
        if threshold < 0 or threshold > 1:
            return False

        with self.lock:
            self.config.CONFIDENCE_THRESHOLD = threshold

        return True

    def is_model_loaded(self) -> bool:
        """
        Check if model is loaded.

        Returns:
            bool: True if model is loaded
        """
        return self.model_manager is not None

    def acceleration_type(self) -> str:
        """
        Get the hardware acceleration type.

        Returns:
            str: "GPU", "CPU", "Disabled", or "None"
        """
        if self.model_manager is not None:
            return self.model_manager.acceleration_type
        return "None"

    def runtime_api(self) -> str:
        """
        Get the runtime API being used.

        Returns:
            str: Active runtime name. TensorRT is the only supported runtime.
        """
        if self.model_manager is not None:
            return self.model_manager.runtime_api
        return "Unknown"

    def _model_name(self) -> str:
        """Basename of the active model file (snapshot/backlog metadata)."""
        return self.config.MODEL_PATH.split('/')[-1]

    @staticmethod
    def _detection_dicts(result: DetectionResult) -> List[dict]:
        """Per-detection dicts in the snapshot wire format.

        Shared by detections_snapshot() and the offline-buffer hook so
        buffered backlog records stay byte-identical to live snapshots.
        """
        height, width = result.processed_image.shape[:2]
        return [
            {
                "class_name": d.class_name,
                "color": d.color,
                "confidence": round(float(d.confidence), 4),
                "area": d.area,
                "bbox": normalized_bbox(d.bbox, width, height),
            }
            for d in result.detections
        ]

    def _pending_backlog(self) -> int:
        """Buffered offline records awaiting a hub drain (0 without a buffer)."""
        return self.buffer_service.pending_count() if self.buffer_service else 0

    def detections_snapshot(self, include_frame: bool = True,
                            include_raw_frame: bool = False) -> dict:
        """Build the latest-detections snapshot.

        Owns the business logic for `/api/v1/detections/snapshot` and the gRPC
        `Snapshot` RPC — both are thin adapters over this. Returns a dict with
        the per-detection list (each tagged with the saved area its center
        falls in, or None, plus its normalized bbox corners), totals,
        model/runtime metadata, the processed frame as a base64 JPEG (when
        ``include_frame``) and the clean frame — no overlay — as ``raw_frame``
        (when ``include_raw_frame``; used by the hub for dataset ingest).
        """
        result = self.last_detection_result
        meta = {
            "model": self._model_name(),
            "acceleration_type": self.acceleration_type(),
            "runtime_type": self.runtime_api(),
            "pending_backlog": self._pending_backlog(),
        }

        if result is None:
            return {"detections": [], "total": 0, "frame": None,
                    "raw_frame": None, **meta}

        detections = self._detection_dicts(result)

        frame_b64 = None
        if include_frame and result.processed_image is not None:
            frame_b64 = _encode_frame_b64(result.processed_image)

        raw_b64 = None
        if include_raw_frame and result.raw_image is not None:
            raw_b64 = _encode_frame_b64(result.raw_image)

        return {
            "detections": detections,
            "total": result.num_detections,
            "frame": frame_b64,
            "raw_frame": raw_b64,
            **meta,
        }

    # ── Trigger control ────────────────────────────────────────────────────────

    def enable_trigger(self) -> None:
        """Enable frame processing trigger."""
        with self.lock:
            self.trigger_enabled = True
        logger.info("Trigger enabled")

    def disable_trigger(self) -> None:
        """Disable frame processing trigger (freeze last frame)."""
        with self.lock:
            self.trigger_enabled = False
        logger.info("Trigger disabled")

    def get_trigger_status(self) -> bool:
        """Return current trigger state."""
        return self.trigger_enabled

    # ── Detection counter ──────────────────────────────────────────────────────

    def get_detection_count(self) -> int:
        """Return accumulated detection count."""
        with self._count_lock:
            return self._detection_count

    def increment_detection_count(self, n: int = 1) -> None:
        """Increment the detection counter by *n*."""
        with self._count_lock:
            self._detection_count += n

    def reset_detection_count(self) -> None:
        """Reset the detection counter to zero."""
        with self._count_lock:
            self._detection_count = 0
