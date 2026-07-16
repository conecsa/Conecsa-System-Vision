"""Processed-frame shared-memory ring (inference-service → api-gateway).

The inference pipeline produces ONE encoded JPEG per processed camera frame
(~45 fps). The headless inference-service publishes it here; the api-gateway
fans it out to MJPEG clients without the frames crossing gRPC. Single producer
(the encode stage), many readers (the gateway's processed feed), latest-wins.

Mirrors the camera ring's flip protocol: write the inactive slot, flip
``active_slot``, then bump ``write_seq`` (release). Both ends are Python, so the
header is our own (little-endian). The segment lives in ``/dev/shm`` and is
shared across containers via the same ``ipc:`` namespace as the camera ring.
"""
import logging
import mmap
import os
import struct
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _default_name() -> str:
    """Segment name from ``PROCESSED_SHM_NAME`` (default ``conecsa_processed_shm``)."""
    return os.environ.get("PROCESSED_SHM_NAME", "conecsa_processed_shm")


def _default_slot_bytes() -> int:
    """Per-slot size from ``PROCESSED_SHM_SLOT_BYTES`` (default 1 MiB)."""
    return int(os.environ.get("PROCESSED_SHM_SLOT_BYTES", str(1 << 20)))  # 1 MiB/slot


SLOTS = 2
MAGIC = 0xC04E5A02
VERSION = 1
HEADER_SIZE = 64

_OFF_MAGIC = 0          # u32
_OFF_VERSION = 4        # u32
_OFF_SLOT_BYTES = 8     # u32
_OFF_ACTIVE_SLOT = 12   # u32
_OFF_FRAME_SIZE = 16    # u32
_OFF_WRITE_SEQ = 24     # u64 (8-byte aligned)


def _path(name: str) -> str:
    """Absolute ``/dev/shm`` path for a segment *name*."""
    return f"/dev/shm/{name}"


class ProcessedFrameWriter:
    """Single-producer writer (the pipeline encode stage)."""

    def __init__(self, shm_name: Optional[str] = None, slot_bytes: Optional[int] = None):
        self._name = shm_name or _default_name()
        self._slot_bytes = slot_bytes or _default_slot_bytes()
        total = HEADER_SIZE + SLOTS * self._slot_bytes
        fd = os.open(_path(self._name), os.O_CREAT | os.O_RDWR, 0o660)
        try:
            os.ftruncate(fd, total)
            self._mm = mmap.mmap(fd, total)
        finally:
            os.close(fd)
        struct.pack_into("<III", self._mm, _OFF_MAGIC, MAGIC, VERSION, self._slot_bytes)
        struct.pack_into("<I", self._mm, _OFF_ACTIVE_SLOT, 0)
        struct.pack_into("<I", self._mm, _OFF_FRAME_SIZE, 0)
        struct.pack_into("<Q", self._mm, _OFF_WRITE_SEQ, 0)
        self._seq = 0
        self._warned = False
        logger.info("[ProcessedSHM] created %s (%d slots x %d bytes)",
                    _path(self._name), SLOTS, self._slot_bytes)

    def publish(self, jpg: bytes) -> None:
        """Publish the latest JPEG. Best-effort: never raises into the hot path."""
        try:
            n = len(jpg)
            if n > self._slot_bytes:
                if not self._warned:
                    logger.warning("[ProcessedSHM] frame %d > slot %d; dropping (logged once)",
                                   n, self._slot_bytes)
                    self._warned = True
                return
            active = struct.unpack_from("<I", self._mm, _OFF_ACTIVE_SLOT)[0]
            write_slot = 1 - active
            base = HEADER_SIZE + write_slot * self._slot_bytes
            self._mm[base:base + n] = jpg
            struct.pack_into("<I", self._mm, _OFF_FRAME_SIZE, n)
            struct.pack_into("<I", self._mm, _OFF_ACTIVE_SLOT, write_slot)
            self._seq += 1
            struct.pack_into("<Q", self._mm, _OFF_WRITE_SEQ, self._seq)
        except Exception as exc:  # noqa: BLE001 - never break the pipeline
            logger.debug("[ProcessedSHM] publish failed: %s", exc)

    def close(self) -> None:
        """Unmap the segment (best-effort)."""
        try:
            self._mm.close()
        except Exception:  # noqa: BLE001
            pass


class ProcessedFrameReader:
    """Multi-consumer reader (the gateway processed-feed fan-out)."""

    def __init__(self, shm_name: Optional[str] = None):
        self._name = shm_name or _default_name()
        self._mm: Optional[mmap.mmap] = None
        self._slot_bytes = _default_slot_bytes()
        self._open()

    def _open(self) -> None:
        """Map the segment read-only, validating magic/version. No-op if absent.

        Lazy: the producer may not have created the segment yet, so this is
        retried by :meth:`get_latest`.
        """
        path = _path(self._name)
        if not os.path.exists(path):
            return
        try:
            fd = os.open(path, os.O_RDONLY)
            size = os.fstat(fd).st_size
            mm = mmap.mmap(fd, size, prot=mmap.PROT_READ)
            os.close(fd)
            magic, version, slot_bytes = struct.unpack_from("<III", mm, _OFF_MAGIC)
            if magic != MAGIC or version != VERSION:
                mm.close()
                logger.warning("[ProcessedSHM] bad magic/version on %s", path)
                return
            self._slot_bytes = slot_bytes
            self._mm = mm
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ProcessedSHM] reader open failed: %s", exc)

    def is_available(self) -> bool:
        """True once the segment has been mapped."""
        return self._mm is not None

    def get_latest(self, last_seq: int) -> Optional[Tuple[bytes, int]]:
        """Return ``(jpeg, seq)`` for the newest frame if ``seq > last_seq``."""
        if self._mm is None:
            self._open()
            if self._mm is None:
                return None
        try:
            seq = struct.unpack_from("<Q", self._mm, _OFF_WRITE_SEQ)[0]
            if seq <= last_seq:
                return None
            active = struct.unpack_from("<I", self._mm, _OFF_ACTIVE_SLOT)[0]
            size = struct.unpack_from("<I", self._mm, _OFF_FRAME_SIZE)[0]
            base = HEADER_SIZE + active * self._slot_bytes
            return bytes(self._mm[base:base + size]), seq
        except Exception as exc:  # noqa: BLE001
            logger.debug("[ProcessedSHM] read failed: %s", exc)
            return None

    def close(self) -> None:
        """Unmap the segment if it was open."""
        if self._mm is not None:
            self._mm.close()
            self._mm = None
