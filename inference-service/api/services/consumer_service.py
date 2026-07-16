"""
Consumer service - owns the shared-memory transport with the webcam-server.

A single always-on background thread polls the POSIX SHM segment and publishes
the latest frame (cheap: just stores the JPEG bytes + a monotonically increasing
sequence number; no decode here). The processing pipeline reads from this
latest-frame slot, so the capture is consumed once regardless of how many
pipeline lanes are attached.

This used to live inside ``VideoService``; it was extracted so the SHM
read/transport is an independent service (and so the heavy decode/inference work
moves to the processing pipeline's own threads).
"""
import logging
import threading
import time
from typing import Optional, Tuple

# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

from conecsa_shm.camera_ring import CameraRingReader

# api/proto is created by Dockerfile.inference-service (and shimmed onto sys.path by
# tests/conftest.py); it does not exist in the checkout, so it is unresolvable statically.
from ..proto import shm_pb2  # pyright: ignore[reportMissingImports]
from .frame_codec import encode_frame

logger = logging.getLogger(__name__)


class ConsumerService:
    """Reads frames from the webcam-server SHM segment and fans them out."""

    def __init__(self, shm_name: str):
        # writable=True: the camera config/health channel writes back through the
        # same segment (CameraRingReader replaces the old in-house ShmConsumer).
        self._shm = CameraRingReader(shm_name, writable=True)

        # Shared latest frame — written by the background reader, read by the
        # processing pipeline. Protected by _cond.
        self._latest_jpg: Optional[bytes] = None
        self._latest_npy: Optional[np.ndarray] = None
        self._seq = 0  # monotonically increasing
        self._cond = threading.Condition(threading.Lock())

        self._thread = threading.Thread(
            target=self._reader, daemon=True, name="webcam-reader"
        )
        self._thread.start()
        logger.info("[ConsumerService] Background camera reader started (/%s)", shm_name)

    # ------------------------------------------------------------------
    # Background reader
    # ------------------------------------------------------------------

    def _reader(self) -> None:
        """Poll the SHM segment for new frames and publish the latest."""
        last_cam_seq = 0
        while True:
            if not self._shm.is_available():
                time.sleep(0.5)
                self._shm.open()
                continue

            result = self._shm.get_latest_frame(last_cam_seq)
            if result is not None:
                frame_data, last_cam_seq = result

                if isinstance(frame_data, np.ndarray):
                    # Raw-RGB producer → already a BGR ndarray. Encode a JPEG so
                    # the raw passthrough stream keeps working.
                    npy = frame_data
                    jpg = encode_frame(npy)
                else:
                    # JPEG producer (common path): keep only the bytes and defer
                    # decoding to the pipeline, which decodes at a reduced scale
                    # on its own worker thread. This keeps the reader cheap enough
                    # to track the full capture fps.
                    jpg = frame_data
                    npy = None

                with self._cond:
                    self._latest_jpg = jpg
                    self._latest_npy = npy
                    self._seq += 1
                    self._cond.notify_all()
            else:
                time.sleep(0.001)  # 1 ms poll interval

    # ------------------------------------------------------------------
    # Latest-frame access (fan-out)
    # ------------------------------------------------------------------

    def wait_for(
        self, last_seq: int, timeout: float = 5.0
    ) -> Tuple[int, Optional[bytes], Optional[np.ndarray]]:
        """Block until a frame newer than ``last_seq`` arrives (or timeout).

        Returns ``(seq, jpg, npy)``; ``seq`` equals ``last_seq`` (with ``None``
        payloads) when the wait timed out without a new frame.
        """
        with self._cond:
            self._cond.wait_for(lambda: self._seq > last_seq, timeout=timeout)
            if self._seq > last_seq:
                return self._seq, self._latest_jpg, self._latest_npy
            return last_seq, None, None

    # ------------------------------------------------------------------
    # Config / health passthrough (same SHM segment)
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """True once the camera SHM segment is mapped."""
        return self._shm.is_available()

    def write_config(self, config) -> None:
        """Write a CameraConfig back into the SHM header for the webcam-server."""
        self._shm.write_config_bytes(config.SerializeToString())

    def read_health(self):
        """Return the webcam-server's HealthStatus from SHM, or ``None``."""
        data = self._shm.read_health_bytes()
        if not data:
            return None
        status = shm_pb2.HealthStatus()
        status.ParseFromString(data)
        return status
