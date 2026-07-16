"""
Shared-memory channel for the GPIO trigger gate (inference-service side).

Mirror of `os-base/agent/gpio_shm.py` — keep the layout in sync. The per-frame
trigger gate reads this mmap'd file (shared with the `os` agent via a volume
mounted in both containers) instead of gRPC, so the inference loop adds no
cross-container round-trip per frame. Output pins are driven over gRPC and never
touch this channel — inference only reads the trigger level here.

Layout (1 byte each; single writer per field → atomic without locking):

    [0] version    (agent)
    [1] available  (agent)
    [2] enabled    (agent)
    [3] trigger    (agent)
"""
import mmap
import os

SHM_PATH = os.environ.get("GPIO_SHM_PATH", "/run/conecsa-gpio/state")
SIZE = 8

_OFF_AVAILABLE = 1
_OFF_ENABLED = 2
_OFF_TRIGGER = 3


class GpioShm:
    """Thin accessor over the mmap'd state file."""

    def __init__(self, mm: mmap.mmap):
        self._mm = mm

    @classmethod
    def attach(cls) -> "GpioShm":
        """Attach to the state file created by the agent. Raises OSError if the
        agent has not created it yet."""
        fd = os.open(SHM_PATH, os.O_RDWR)
        try:
            mm = mmap.mmap(fd, SIZE)
        finally:
            os.close(fd)
        return cls(mm)

    @property
    def available(self) -> bool:
        return bool(self._mm[_OFF_AVAILABLE])

    @property
    def enabled(self) -> bool:
        return bool(self._mm[_OFF_ENABLED])

    @property
    def trigger(self) -> bool:
        return bool(self._mm[_OFF_TRIGGER])

    def close(self) -> None:
        """Unmap the GPIO state file (best-effort)."""
        try:
            self._mm.close()
        except Exception:  # noqa: BLE001
            pass
