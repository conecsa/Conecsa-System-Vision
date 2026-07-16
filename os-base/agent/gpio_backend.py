"""
GPIO hardware backend — a small typed interface over the 40-pin header.

The agent logic (poll loop, status, per-pin writes) talks to GPIO through this
interface instead of importing ``Jetson.GPIO`` directly, so the hardware
specifics (BOARD numbering, pinmux register pokes, the untyped vendor library)
stay in one place. Two implementations:

- :class:`JetsonGpioBackend` — real hardware via ``Jetson.GPIO`` (BOARD mode),
  forcing the output pads off their reserved pinmux function so they can drive.
- :class:`NullGpioBackend` — a no-op fallback for dev boxes / when the library
  or hardware is missing, so the agent still serves the rest of HardwareService.

Use :func:`create_gpio_backend` to pick the right one.
"""
import logging
import mmap
import struct
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class GpioBackend(ABC):
    """Minimal GPIO operations the agent needs (BOARD pin numbering)."""

    @property
    @abstractmethod
    def available(self) -> bool:
        """True when backed by real, initialised GPIO hardware."""

    @abstractmethod
    def setup_input(self, pin: int) -> None:
        """Configure *pin* as a digital input."""

    @abstractmethod
    def setup_output(self, pin: int, initial: bool = False) -> None:
        """Configure *pin* as a digital output, driven to *initial*."""

    @abstractmethod
    def read(self, pin: int) -> bool:
        """Return the current level of an input *pin*."""

    @abstractmethod
    def write(self, pin: int, level: bool) -> None:
        """Drive an output *pin* HIGH (True) or LOW (False)."""

    @abstractmethod
    def cleanup(self) -> None:
        """Release any claimed pins (best-effort)."""


class JetsonGpioBackend(GpioBackend):
    """Real ``Jetson.GPIO`` backend (BOARD numbering) with pinmux configuration."""

    # Pinmux register (addr, value) for each output pin that defaults to a
    # reserved/non-GPIO function with tristate enabled on this board. Written to
    # /dev/mem (little-endian word) so the pad drives as GPIO output. Pins absent
    # here are assumed to already default to GPIO.
    _PINMUX: dict[int, tuple[int, int]] = {
        29: (0x2430068, 0x8),
        31: (0x2430070, 0x8),
        33: (0x2434040, 0x4),
    }

    def __init__(self) -> None:
        # Raises (ImportError / RuntimeError) when the library or hardware is
        # missing; the factory turns that into a NullGpioBackend.
        import Jetson.GPIO as GPIO
        self._gpio = GPIO
        self._gpio.setmode(self._gpio.BOARD)

    @property
    def available(self) -> bool:
        return True

    def setup_input(self, pin: int) -> None:
        self._gpio.setup(pin, self._gpio.IN)

    def setup_output(self, pin: int, initial: bool = False) -> None:
        self._configure_pinmux(pin)
        self._gpio.setup(pin, self._gpio.OUT,
                         initial=self._gpio.HIGH if initial else self._gpio.LOW)

    def read(self, pin: int) -> bool:
        return bool(self._gpio.input(pin))

    def write(self, pin: int, level: bool) -> None:
        self._gpio.output(pin, self._gpio.HIGH if level else self._gpio.LOW)

    def cleanup(self) -> None:
        self._gpio.cleanup()

    def _configure_pinmux(self, pin: int) -> None:
        """Force *pin*'s pad to GPIO via a /dev/mem pinmux write (non-fatal)."""
        cfg = self._PINMUX.get(pin)
        if cfg is None:
            return
        addr, value = cfg
        page_size = mmap.PAGESIZE
        try:
            with open("/dev/mem", "r+b") as devmem:
                page_base = addr & ~(page_size - 1)
                page_offset = addr & (page_size - 1)
                with mmap.mmap(devmem.fileno(), page_size, offset=page_base) as m:
                    m[page_offset : page_offset + 4] = struct.pack("<I", value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not configure pinmux for pin %d (non-fatal): %s", pin, exc)


class NullGpioBackend(GpioBackend):
    """No-op backend used when GPIO hardware/library is unavailable."""

    @property
    def available(self) -> bool:
        return False

    def setup_input(self, pin: int) -> None:
        pass

    def setup_output(self, pin: int, initial: bool = False) -> None:
        pass

    def read(self, pin: int) -> bool:
        return False

    def write(self, pin: int, level: bool) -> None:
        pass

    def cleanup(self) -> None:
        pass


def create_gpio_backend() -> GpioBackend:
    """Return a real Jetson backend if GPIO is present, else a no-op backend."""
    try:
        backend = JetsonGpioBackend()
        logger.info("GPIO backend: Jetson.GPIO (BOARD mode)")
        return backend
    except Exception as exc:  # noqa: BLE001
        logger.warning("GPIO not available (non-fatal): %s", exc)
        return NullGpioBackend()
