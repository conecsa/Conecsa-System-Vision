"""
GPIO Service — client to the `os` hardware agent.

The GPIO hardware (trigger input + output pins) is owned by the `os` container's
agent. The only per-frame hot path is the trigger gate (`should_process_frame`),
which reads the trigger pin level over a shared-memory channel (gpio_shm) — no
gRPC per frame. Output-pin control and config-style ops (enable/status) are
served by the agent's gRPC directly to the api-gateway and do not pass through
this service.

If the agent/SHM is not (yet) available the service is transparent: every frame
is processed, matching the old "GPIO disabled" behavior.
"""
import logging
import time

from .gpio_shm import GpioShm

logger = logging.getLogger(__name__)

_ATTACH_RETRY_S = 2.0


class GPIOService:
    """Per-frame trigger gate, backed by the os agent over SHM."""

    def __init__(self):
        self._shm: GpioShm | None = None
        self._last_attach = 0.0
        self._ensure_shm()

    # ── shared-memory attach (lazy; agent creates the segment) ───────────────────

    def _ensure_shm(self) -> "GpioShm | None":
        """Lazily attach to the GPIO SHM channel (the `os` agent creates it).

        Returns the handle, or ``None`` while the agent is not up yet, retrying
        no more than once every ``_ATTACH_RETRY_S``.
        """
        if self._shm is not None:
            return self._shm
        now = time.monotonic()
        if now - self._last_attach < _ATTACH_RETRY_S:
            return None
        self._last_attach = now
        try:
            self._shm = GpioShm.attach()
            logger.info("GPIO shared-memory channel attached")
        except OSError:
            self._shm = None  # agent not up yet — retry later
        return self._shm

    # ── frame gate (hot path) ─────────────────────────────────────────────────────

    def should_process_frame(self) -> bool:
        """True if this frame should be processed (the GPIO trigger gate).

        Transparent (always True) when GPIO is unavailable or trigger mode is
        disabled; otherwise mirrors the current trigger pin level.
        """
        shm = self._ensure_shm()
        if shm is None or not shm.available or not shm.enabled:
            return True  # transparent when GPIO is unavailable/disabled
        return shm.trigger
