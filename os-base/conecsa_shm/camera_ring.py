"""Camera shared-memory ring reader (produced by the Rust webcam-server).

Single source of the camera-ring header layout — must match
``webcam-server/src/webcam_server/shm.rs``. Used by:

- **inference-service** (``ConsumerService``): ``get_latest_frame`` returns the
  raw form (BGR ``np.ndarray`` for RAW_RGB producers, JPEG ``bytes`` for MJPEG),
  plus the camera config/health byte exchange (``writable=True``).
- **api-gateway** (``media``): ``get_latest`` returns a ready-to-stream JPEG
  (RAW frames are encoded), read-only, lock-free across many MJPEG generators.

Readers are stateless (the caller passes the last seq it saw), so any number of
consumers fan out from the same segment.
"""
import logging
import mmap
import os
import struct
from typing import Optional, Tuple, Union

# numpy/cv2 ship in conecsa-os:base.
import numpy as np
import cv2

logger = logging.getLogger(__name__)

# Header constants — must match webcam-server/src/webcam_server/shm.rs.
SHM_MAGIC = 0xC04E5A01
SHM_VERSION = 1
HEADER_SIZE = 256
CONFIG_PAYLOAD_MAX = 128
HEALTH_PAYLOAD_MAX = 64

FORMAT_RAW_RGB = 0
FORMAT_JPEG = 1

OFF_MAGIC = 0
OFF_VERSION = 4
OFF_WIDTH = 8
OFF_HEIGHT = 12
OFF_CHANNELS = 16
OFF_MAX_FRAME_BYTES = 20
OFF_FRAME_WRITE_SEQ = 24  # u64
OFF_ACTIVE_SLOT = 32
OFF_FORMAT_FLAG = 36
OFF_FRAME_SIZE = 40
OFF_CONFIG_WRITE_SEQ = 44
OFF_CONFIG_SIZE = 48
OFF_CONFIG_PAYLOAD = 52
OFF_HEALTH_WRITE_SEQ = 180
OFF_HEALTH_SIZE = 184
OFF_HEALTH_PAYLOAD = 188


class CameraRingReader:
    """Reads the webcam-server camera ring (lock-free, latest-wins)."""

    def __init__(self, shm_name: str, writable: bool = False):
        self._path = f"/dev/shm/{shm_name}"
        self._writable = writable
        self._mm: Optional[mmap.mmap] = None
        self._width = 0
        self._height = 0
        self._channels = 3
        self._slot_size = 0
        self.open()

    def open(self) -> None:
        """Map the camera segment (read-only, or read-write if ``writable``).

        Validates the magic/version and caches the frame geometry from the
        header. No-op if already open or the producer hasn't created it yet.
        """
        if self._mm is not None or not os.path.exists(self._path):
            return
        try:
            flags = os.O_RDWR if self._writable else os.O_RDONLY
            fd = os.open(self._path, flags)
            size = os.fstat(fd).st_size
            if size < HEADER_SIZE:
                os.close(fd)
                return
            access = mmap.ACCESS_WRITE if self._writable else mmap.ACCESS_READ
            mm = mmap.mmap(fd, size, access=access)
            os.close(fd)
            magic, version = struct.unpack_from("<II", mm, OFF_MAGIC)
            if magic != SHM_MAGIC or version != SHM_VERSION:
                mm.close()
                logger.warning("[camera-shm] bad magic/version on %s", self._path)
                return
            self._width = struct.unpack_from("<I", mm, OFF_WIDTH)[0]
            self._height = struct.unpack_from("<I", mm, OFF_HEIGHT)[0]
            self._channels = struct.unpack_from("<I", mm, OFF_CHANNELS)[0]
            self._slot_size = struct.unpack_from("<I", mm, OFF_MAX_FRAME_BYTES)[0]
            self._mm = mm
            logger.info("[camera-shm] opened %s (%dx%d, slot=%d)",
                        self._path, self._width, self._height, self._slot_size)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[camera-shm] open failed: %s", exc)

    def is_available(self) -> bool:
        """True once the camera segment has been mapped."""
        return self._mm is not None

    # ── frames ────────────────────────────────────────────────────────────────

    def get_latest_frame(
        self, last_seq: int
    ) -> Optional[Tuple[Union[np.ndarray, bytes], int]]:
        """Return ``(frame, seq)`` for the newest frame when ``seq > last_seq``.

        RAW_RGB producers → BGR ``np.ndarray``; MJPEG producers → JPEG ``bytes``.
        """
        if self._mm is None:
            self.open()
            if self._mm is None:
                return None
        try:
            seq = struct.unpack_from("<Q", self._mm, OFF_FRAME_WRITE_SEQ)[0]
            if seq <= last_seq:
                return None
            active = struct.unpack_from("<I", self._mm, OFF_ACTIVE_SLOT)[0]
            fmt = struct.unpack_from("<I", self._mm, OFF_FORMAT_FLAG)[0]
            size = struct.unpack_from("<I", self._mm, OFF_FRAME_SIZE)[0]
            base = HEADER_SIZE + active * self._slot_size
            raw = self._mm[base:base + size]
            if fmt == FORMAT_RAW_RGB:
                self._width = struct.unpack_from("<I", self._mm, OFF_WIDTH)[0]
                self._height = struct.unpack_from("<I", self._mm, OFF_HEIGHT)[0]
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(
                    self._height, self._width, self._channels
                )
                return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), seq
            return bytes(raw), seq
        except Exception as exc:  # noqa: BLE001
            logger.debug("[camera-shm] read failed: %s", exc)
            return None

    def get_latest(self, last_seq: int) -> Optional[Tuple[bytes, int]]:
        """Return ``(jpeg, seq)`` for the newest frame — RAW frames are encoded.

        Convenience for MJPEG fan-out (the api-gateway), which only wants JPEG.
        """
        got = self.get_latest_frame(last_seq)
        if got is None:
            return None
        frame, seq = got
        if isinstance(frame, np.ndarray):
            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            return (buf.tobytes(), seq) if ok else None
        return frame, seq

    # ── camera config / health (opaque payloads; writable mapping) ─────────────

    def write_config_bytes(self, payload: bytes) -> None:
        """Publish a serialized camera-config payload for the producer to apply."""
        if self._mm is None or not self._writable:
            return
        if len(payload) > CONFIG_PAYLOAD_MAX:
            logger.error("[camera-shm] config payload too large (%d)", len(payload))
            return
        self._mm[OFF_CONFIG_PAYLOAD:OFF_CONFIG_PAYLOAD + len(payload)] = payload
        struct.pack_into("<I", self._mm, OFF_CONFIG_SIZE, len(payload))
        cur = struct.unpack_from("<I", self._mm, OFF_CONFIG_WRITE_SEQ)[0]
        struct.pack_into("<I", self._mm, OFF_CONFIG_WRITE_SEQ, cur + 1)

    def read_health_bytes(self) -> Optional[bytes]:
        """Return the latest serialized health payload, or ``None``."""
        if self._mm is None:
            return None
        try:
            size = struct.unpack_from("<I", self._mm, OFF_HEALTH_SIZE)[0]
            if size == 0 or size > HEALTH_PAYLOAD_MAX:
                return None
            return bytes(self._mm[OFF_HEALTH_PAYLOAD:OFF_HEALTH_PAYLOAD + size])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[camera-shm] health read failed: %s", exc)
            return None

    def close(self) -> None:
        """Unmap the camera segment if it was open."""
        if self._mm is not None:
            self._mm.close()
            self._mm = None
