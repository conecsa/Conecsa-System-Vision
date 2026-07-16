"""
GpioAgent — owns the Jetson GPIO hardware in the privileged `os` container.

Responsibilities:
  - initialise the GPIO backend (trigger input + output pins);
  - run a small poll loop that publishes the trigger level via the shared-memory
    channel (gpio_shm) — this is the per-frame hot path, kept off gRPC;
  - expose enable/status + per-pin output control for the gRPC HardwareService.

The hardware specifics (Jetson.GPIO, BOARD numbering, pinmux) live behind the
:class:`GpioBackend` interface in ``gpio_backend`` — the agent only speaks in
BOARD pin numbers and HIGH/LOW levels.

Pin assignments (BOARD numbering, Jetson Orin Nano 40-pin header):
  pin 7 = trigger input; pins 29/31/33 = controllable digital outputs.
"""
import logging
import os
import threading
import time

from .gpio_backend import GpioBackend, create_gpio_backend
from .gpio_shm import OUTPUT_PINS, TRIGGER_INPUT_PIN, GpioShm

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = float(os.environ.get("GPIO_POLL_MS", "5")) / 1000.0


class GpioAgent:
    """Owns GPIO hardware and bridges it to the shared-memory hot path."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._backend: GpioBackend = create_gpio_backend()
        self._shm = GpioShm.create()
        self._pin_states: dict[int, bool] = {pin: False for pin in OUTPUT_PINS}
        self._stop = threading.Event()
        self._init_pins()
        self._shm.available = self._backend.available
        self._thread = threading.Thread(target=self._loop, daemon=True, name="gpio-agent")
        self._thread.start()

    # ── init ─────────────────────────────────────────────────────────────────────

    def _init_pins(self) -> None:
        """Configure the trigger input and the output pins (no-op when absent)."""
        if not self._backend.available:
            return
        try:
            self._backend.setup_input(TRIGGER_INPUT_PIN)
            for pin in OUTPUT_PINS:
                self._backend.setup_output(pin, initial=False)
            logger.info(
                "GPIO initialised — trigger pin %d, output pins %s",
                TRIGGER_INPUT_PIN, OUTPUT_PINS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("GPIO setup failed (non-fatal): %s", exc)

    # ── hot-path poll loop ─────────────────────────────────────────────────────────

    def _loop(self) -> None:
        """Hot-path poll loop: publish the trigger pin level to SHM.

        Runs on a daemon thread every ``GPIO_POLL_MS``. Output pins are driven
        on demand via ``set_pin`` (gRPC), so the loop only mirrors the trigger
        input into the shared-memory channel for the inference frame gate.
        """
        while not self._stop.is_set():
            if self._backend.available:
                try:
                    self._shm.trigger = self._backend.read(TRIGGER_INPUT_PIN)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("trigger read failed: %s", exc)
            time.sleep(_POLL_INTERVAL_S)

    # ── gRPC-backed ops ───────────────────────────────────────────────────────────

    def set_enabled(self, enabled: bool) -> dict:
        """Enable/disable GPIO trigger mode (the per-frame pin-7 frame gate)."""
        with self._lock:
            self._shm.enabled = enabled
        logger.info("GPIO trigger mode %s", "enabled" if enabled else "disabled")
        return {"success": True, "message": f"GPIO trigger {'enabled' if enabled else 'disabled'}"}

    def set_pin(self, pin: int, level: bool) -> dict:
        """Drive a single output pin HIGH/LOW. Rejects non-output pins."""
        if pin not in self._pin_states:
            return {"success": False, "message": f"Pin {pin} is not a controllable output pin"}
        with self._lock:
            if self._backend.available:
                try:
                    self._backend.write(pin, level)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Error driving pin %d: %s", pin, exc)
                    return {"success": False, "message": f"Failed to drive pin {pin}: {exc}"}
            self._pin_states[pin] = level
        return {"success": True, "message": f"Pin {pin} set {'HIGH' if level else 'LOW'}"}

    def get_status(self) -> dict:
        """Return ``{available, enabled, pins}`` for the gRPC status RPC."""
        with self._lock:
            pins = dict(self._pin_states)
        return {
            "available": self._backend.available,
            "enabled": self._shm.enabled,
            "pins": pins,
        }

    def cleanup(self) -> None:
        """Stop the poll loop, release the GPIO pins and close the SHM channel."""
        self._stop.set()
        try:
            self._backend.cleanup()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GPIO cleanup error: %s", exc)
        self._shm.close()
