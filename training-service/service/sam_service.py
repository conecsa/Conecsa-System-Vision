"""SAM3 worker lifecycle + segmentation requests.

Lazy: the worker subprocess (and the ~2-3GB of GPU memory it pins) exists only
while the operator is actively using AI-assisted labeling. Unload = terminate
the subprocess (the only reliable way to return the memory on the 8GB Orin
Nano). An idle timer unloads automatically; TrainingService also unloads
before every training run — SAM and training never share the GPU.

Availability degrades gracefully: when the sam3 package or the (Hugging Face
gated, user-provisioned) checkpoint is missing, ``status()`` reports
available=False and manual labeling is unaffected.
"""
import importlib.util
import logging
import os
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client
from typing import Any, Dict, List, Optional, Tuple

from .config import Config

logger = logging.getLogger(__name__)

_AUTH_KEY = b"conecsa"
_CONNECT_ATTEMPTS = 50
_LOAD_TIMEOUT_S = 300.0     # cold load reads the checkpoint from eMMC/SD
_SEGMENT_TIMEOUT_S = 120.0


class SamService:
    """Manages the on-demand SAM3 segmentation worker subprocess.

    Loads/unloads the (HF-gated) SAM3 checkpoint in a child process to free GPU
    memory between uses, and proxies segmentation requests to it; idle-unloads
    after a timeout.
    """

    def __init__(self, config: Config, event_service=None):
        self._config = config
        self._events = event_service
        self._lock = threading.RLock()
        self._process: Optional[subprocess.Popen] = None
        self._conn: Optional[Any] = None
        self._last_used = 0.0
        self._idle_timer: Optional[threading.Timer] = None

    # ── status / availability ─────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Status."""
        available, message = self._availability()
        return {
            "available": available,
            "loaded": self.is_loaded(),
            "message": message,
        }

    def _availability(self) -> Tuple[bool, str]:
        """Availability."""
        if importlib.util.find_spec("sam3") is None:
            return False, "sam3 package not installed in this image"
        if not os.path.exists(self._config.SAM3_CHECKPOINT):
            return False, (
                f"SAM3 checkpoint not found at {self._config.SAM3_CHECKPOINT} "
                "(gated download — place it in training-service/assets/ and rebuild)"
            )
        return True, ""

    def is_loaded(self) -> bool:
        """Is loaded."""
        with self._lock:
            return self._process is not None and self._process.poll() is None

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Load."""
        with self._lock:
            available, message = self._availability()
            if not available:
                raise RuntimeError(message)
            if self.is_loaded():
                self._touch()
                return
            try:
                self._spawn()
                resp = self._request({"cmd": "load"}, timeout=_LOAD_TIMEOUT_S)
                if resp.get("status") != "ok":
                    raise RuntimeError(resp.get("error", "SAM load failed"))
            except Exception:
                self.unload()
                raise
            self._touch()
        self._publish_state()

    def unload(self) -> None:
        """Unload."""
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            if self._conn is not None:
                try:
                    self._conn.send({"cmd": "close"})
                except OSError:
                    pass
                try:
                    self._conn.close()
                except OSError:
                    pass
                self._conn = None
            if self._process is not None:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=5)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("SAM worker terminate failed: %s", exc)
                self._process = None
                logger.info("SAM worker unloaded")
        self._publish_state()

    # ── segmentation ──────────────────────────────────────────────────────────

    def segment(
        self,
        image_path: str,
        text_prompt: str,
        points: List[Dict[str, Any]],
        threshold: Optional[float] = None,
    ) -> Tuple[List[Dict[str, float]], List[float]]:
        """Segment."""
        with self._lock:
            if not self.is_loaded():
                self.load()
            resp = self._request(
                {
                    "cmd": "segment",
                    "image_path": image_path,
                    "text_prompt": text_prompt or "",
                    "points": points or [],
                    "threshold": threshold,
                },
                timeout=_SEGMENT_TIMEOUT_S,
            )
            self._touch()
        if resp.get("status") != "ok":
            raise RuntimeError(resp.get("error", "Segmentation failed"))
        return resp.get("boxes", []), resp.get("scores", [])

    # ── internals ─────────────────────────────────────────────────────────────

    def _spawn(self) -> None:
        """Spawn."""
        env = os.environ.copy()
        env["PYTHONPATH"] = "/app/training-service"
        log_path = f"/tmp/sam_worker_{self._config.SAM_WORKER_PORT}.log"
        logger.info(
            "Starting SAM worker on port %d, logs: %s",
            self._config.SAM_WORKER_PORT,
            log_path,
        )
        log_file = open(log_path, "w")
        try:
            self._process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "service._sam_worker",
                    "--port",
                    str(self._config.SAM_WORKER_PORT),
                    "--checkpoint",
                    self._config.SAM3_CHECKPOINT,
                ],
                env=env,
                start_new_session=True,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        finally:
            log_file.close()
        last_err: Optional[Exception] = None
        for _ in range(_CONNECT_ATTEMPTS):
            if self._process.poll() is not None:
                raise RuntimeError(
                    f"SAM worker exited at startup (code {self._process.returncode}); "
                    f"see {log_path}"
                )
            try:
                self._conn = Client(
                    ("127.0.0.1", self._config.SAM_WORKER_PORT), authkey=_AUTH_KEY
                )
                return
            except (ConnectionRefusedError, OSError) as exc:
                last_err = exc
                time.sleep(0.2)

        # No connection: ensure we don't leave a stray worker running.
        try:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                self._process.wait(timeout=2)
        except Exception:  # noqa: BLE001
            try:
                if self._process is not None and self._process.poll() is None:
                    self._process.kill()
            except Exception:  # noqa: BLE001
                pass
        finally:
            self._process = None

        raise RuntimeError(f"Could not connect to SAM worker: {last_err}")

    def _request(self, msg: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        """Request."""
        if self._conn is None:
            raise RuntimeError("SAM worker not connected")
        self._conn.send(msg)
        if not self._conn.poll(timeout):
            self.unload()
            raise RuntimeError("SAM worker timed out; it was unloaded")
        try:
            return self._conn.recv()
        except EOFError:
            # The worker died mid-request — on the 8GB Orin Nano that is
            # almost always the kernel OOM killer.
            self.unload()
            raise RuntimeError(
                "SAM worker died mid-request (likely out of memory); "
                f"see /tmp/sam_worker_{self._config.SAM_WORKER_PORT}.log"
            )

    def _touch(self) -> None:
        """Touch."""
        self._last_used = time.monotonic()
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        self._idle_timer = threading.Timer(
            self._config.SAM_IDLE_UNLOAD_SEC, self._idle_unload
        )
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _idle_unload(self) -> None:
        """Idle unload."""
        idle = time.monotonic() - self._last_used
        if self.is_loaded() and idle >= self._config.SAM_IDLE_UNLOAD_SEC - 1:
            logger.info("SAM worker idle for %.0fs; unloading", idle)
            self.unload()

    def _publish_state(self) -> None:
        """Publish state."""
        if self._events is None:
            return
        try:
            self._events.publish("sam_changed", keys=["sam"], data=self.status())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not publish sam event: %s", exc)
