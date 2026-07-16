"""
Statistics service - Manages performance statistics.
"""
import threading
from typing import Optional
from ..models.detection_models import SystemStats


class StatsService:
    """Service for managing system statistics."""

    def __init__(self):
        """Initialize the stats service."""
        self.stats = SystemStats()
        # Protects update()/reset() against concurrent readers so nothing
        # observes a partially-updated snapshot (or a stats object swapped out
        # by reset() mid-read).
        self._lock = threading.Lock()
        # Optional sink (EventService.publish_stats) so stats flow down the
        # unified app-event stream, letting clients use a single connection
        # instead of a dedicated stats stream. Invoked under ``self._lock``
        # with the full stats dict on every update/reset.
        self._update_listener = None

    def set_update_listener(self, listener) -> None:
        """Register a callback fired with the stats dict on every update."""
        self._update_listener = listener

    def update(self, fps: Optional[float] = None, inference_time: Optional[float] = None,
               detections: Optional[int] = None, increment_frames_with_detections: bool = False):
        """
        Update statistics.

        Args:
            fps: Frames per second
            inference_time: Inference time in milliseconds
            detections: Number of detections
            increment_frames_with_detections: Whether to increment frames with detections counter
        """
        with self._lock:
            if fps is not None:
                self.stats.fps = fps

            if inference_time is not None:
                self.stats.inference_time = inference_time

            if detections is not None:
                self.stats.detections = detections

            if increment_frames_with_detections:
                self.stats.frames_with_detections += 1

            self._fanout_locked()

    def get_stats(self) -> SystemStats:
        """Get a consistent snapshot of the current statistics."""
        with self._lock:
            return SystemStats(
                fps=self.stats.fps,
                inference_time=self.stats.inference_time,
                detections=self.stats.detections,
                frames_with_detections=self.stats.frames_with_detections,
            )

    def reset(self):
        """Reset all statistics to zero."""
        with self._lock:
            self.stats = SystemStats()
            self._fanout_locked()

    def _fanout_locked(self) -> None:
        """Mirror the latest stats to the registered listener (if any).

        Caller must hold ``self._lock``. The listener (EventService) takes its
        own lock; nothing acquires ``self._lock`` while holding the event lock,
        so there is no inversion.
        """
        if self._update_listener is not None:
            try:
                self._update_listener(self._to_dict_locked())
            except Exception:  # noqa: BLE001
                pass

    def _to_dict_locked(self) -> dict:
        """Build the stats dict. Caller must hold ``self._lock``."""
        return {
            "fps": self.stats.fps,
            "inference_time": self.stats.inference_time,
            "detections": self.stats.detections,
            "frames_with_detections": self.stats.frames_with_detections
        }
