"""
Shared-memory channel for the GPIO trigger gate (hot path).

The per-frame trigger gate must NOT cross a gRPC boundary (the inference loop
runs at ~45 fps). Instead the `os` agent (which owns the GPIO hardware) and
inference-service share a tiny mmap'd file on a volume mounted in both
containers. mmap MAP_SHARED on the same host inode is shared across mount
namespaces, so writes are visible to the other container immediately.

Output pins (29/31/33) are driven on demand over gRPC (SetGpioPin),
not over this channel — they are event-style, not per-frame, so they do not need
the SHM hot path. Only the trigger input ride it.

Layout (1 byte each; every field has a single writer, so byte accesses are
atomic without locking):

    [0] version    (agent)
    [1] available  (agent)   — GPIO hardware initialised
    [2] enabled    (agent)   — trigger/gate mode on (set via gRPC SetGpioTrigger)
    [3] trigger    (agent)   — current trigger pin level

Pin assignments are documented here so both sides agree on the wiring (only the
agent actually drives them).
"""
import mmap
import os

SHM_PATH = os.environ.get("GPIO_SHM_PATH", "/run/conecsa-gpio/state")
SIZE = 8
VERSION = 2  # 2: dropped the binary-count byte; output pins moved to gRPC

_OFF_VERSION = 0
_OFF_AVAILABLE = 1
_OFF_ENABLED = 2
_OFF_TRIGGER = 3

# BOARD-mode pin numbers (Jetson Orin Nano 40-pin header).
TRIGGER_INPUT_PIN = 7
OUTPUT_PINS = [29, 31, 33]  # freely-controllable digital outputs


class GpioShm:
    """Thin accessor over the mmap'd state file."""

    def __init__(self, mm: mmap.mmap):
        self._mm = mm

    @classmethod
    def create(cls) -> "GpioShm":
        """Create/truncate the state file (agent side)."""
        os.makedirs(os.path.dirname(SHM_PATH), exist_ok=True)
        fd = os.open(SHM_PATH, os.O_CREAT | os.O_RDWR, 0o660)
        try:
            os.ftruncate(fd, SIZE)
            mm = mmap.mmap(fd, SIZE)
        finally:
            os.close(fd)  # the mapping stays valid after closing the fd
        mm[_OFF_VERSION] = VERSION
        return cls(mm)

    @classmethod
    def attach(cls) -> "GpioShm":
        """Attach to an existing state file (client side). Raises OSError if the
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

    @available.setter
    def available(self, value: bool) -> None:
        self._mm[_OFF_AVAILABLE] = 1 if value else 0

    @property
    def enabled(self) -> bool:
        return bool(self._mm[_OFF_ENABLED])

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._mm[_OFF_ENABLED] = 1 if value else 0

    @property
    def trigger(self) -> bool:
        return bool(self._mm[_OFF_TRIGGER])

    @trigger.setter
    def trigger(self, value: bool) -> None:
        self._mm[_OFF_TRIGGER] = 1 if value else 0

    def close(self) -> None:
        """Unmap the state file (best-effort; errors are swallowed)."""
        try:
            self._mm.close()
        except Exception:  # noqa: BLE001
            pass
