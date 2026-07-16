"""Orphaned-training-mode watchdog.

Training mode (inference runtime released) is entered and exited only by
explicit client calls — normally the hub's federated coordinator or the
device UI. If that client dies mid-run (hub powered off), nothing ever calls
``/training/exit`` and the device sits with detection stopped forever.

The tracker arms when training mode is entered (or a training run starts),
every ``/api/v1/training/*`` request touches it (the hub polls status every
2s while alive), and once armed-and-idle past TRAINING_ORPHAN_TIMEOUT_SEC it
exits training mode itself, resuming detection. It never fires while a
training job is active — long runs are legitimately quiet on HTTP and the
trainer's own stall watchdog guards them device-side — nor while a model
conversion runs (never resume the runtime under a TensorRT build).

``TRAINING_ORPHAN_TIMEOUT_SEC=0`` disables the watchdog.
"""
import logging
import threading
import time

import grpc

from ..config import settings
from ..grpc_clients import clients, inf, trn

logger = logging.getLogger(__name__)

#: Device job statuses during which the watchdog must never fire.
_ACTIVE_JOB = ("preparing", "training", "uploading")
#: Conversion statuses meaning a TensorRT build may hold the GPU.
_ACTIVE_CONVERSION = ("pending", "converting_to_onnx", "converting_to_engine")

_TICK_SEC = 30.0


class OrphanTracker:
    """Arms on training-mode entry, fires an auto-exit after client silence."""

    def __init__(self, timeout_sec: float | None = None):
        self._timeout = (settings.TRAINING_ORPHAN_TIMEOUT_SEC
                         if timeout_sec is None else timeout_sec)
        self._lock = threading.Lock()
        self._armed = False
        self._last_activity = 0.0

    @property
    def armed(self) -> bool:
        with self._lock:
            return self._armed

    def arm(self) -> None:
        """Start (or restart) the idle countdown — training mode was entered."""
        with self._lock:
            self._armed = True
            self._last_activity = time.monotonic()

    def touch(self) -> None:
        """Reset the idle countdown; a no-op while disarmed.

        Registered as a ``before_request`` hook on the training blueprint, so
        it must return ``None`` (any other value would short-circuit Flask).
        """
        with self._lock:
            if self._armed:
                self._last_activity = time.monotonic()

    def disarm(self) -> None:
        """Stop the countdown — training mode was exited."""
        with self._lock:
            self._armed = False

    def start(self) -> None:
        """Spawn the daemon watchdog thread (no-op when disabled)."""
        if self._timeout <= 0:
            logger.info("Training orphan watchdog disabled (timeout=0)")
            return
        threading.Thread(target=self._run, name="orphan-watchdog",
                         daemon=True).start()

    def _run(self) -> None:
        self._recover()
        while True:
            time.sleep(_TICK_SEC)
            try:
                self.check_once()
            except Exception:  # noqa: BLE001 - the watchdog must survive anything
                logger.exception("Orphan watchdog tick failed")

    def _recover(self) -> None:
        """Re-arm after a gateway restart mid-run: an active training job
        means some client entered training mode before this process came up."""
        try:
            job = clients.training.GetTraining(trn.Empty())
        except grpc.RpcError:
            return
        if job.status in _ACTIVE_JOB:
            logger.info("Active training job found at startup; arming the "
                        "orphan watchdog")
            self.arm()

    def check_once(self) -> None:
        """One watchdog tick: fire the auto-exit when armed and idle too long."""
        with self._lock:
            armed = self._armed
            idle = time.monotonic() - self._last_activity
        if not armed or idle <= self._timeout:
            return
        # An actively-training device is legitimately quiet on HTTP; probe
        # failures skip the tick (state unknown — retry on the next one).
        try:
            job = clients.training.GetTraining(trn.Empty())
        except grpc.RpcError:
            return
        if job.status in _ACTIVE_JOB:
            self.touch()
            return
        try:
            cl = clients.model.ListConversions(inf.Empty())
        except grpc.RpcError:
            return
        if any(j.status in _ACTIVE_CONVERSION for j in cl.jobs):
            self.touch()
            return
        # Re-check the idle window under the lock in case a request touched the
        # tracker while we were probing gRPC state.
        with self._lock:
            if not self._armed:
                return
            idle = time.monotonic() - self._last_activity
        if idle <= self._timeout:
            return
        logger.warning("Training mode idle for %.0fs with no client activity "
                       "— auto-exiting and resuming detection", idle)
        from .session import _do_exit  # runtime import: session imports this module
        try:
            ok, msg = _do_exit(resume_detection=True)
        except grpc.RpcError as exc:
            detail = exc.details() if hasattr(exc, "details") else str(exc)
            ok, msg = False, detail
        if ok:
            self.disarm()
        else:
            logger.error("Orphan auto-exit failed (%s); retrying on the next "
                         "tick", msg)


tracker = OrphanTracker()
