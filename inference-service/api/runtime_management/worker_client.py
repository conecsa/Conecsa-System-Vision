"""
Client for the TensorRT runtime worker subprocess.
"""
import logging
import os
import sys
import time
import subprocess
from subprocess import TimeoutExpired
from multiprocessing.connection import Client
from threading import RLock
from typing import Any, Dict, List, Optional

# noinspection PyPackageRequirements
import numpy as np # Package is included on os build.

logger = logging.getLogger(__name__)

AUTH_KEY = b"conecsa"
DEFAULT_HOST = "127.0.0.1"
WORKER_NAME = "tensorrt"


def _validate_response(resp: Dict[str, Any], default_error: str) -> None:
    """
    Validate response status and raise error if not ok.

    Args:
        resp: Response dictionary from worker
        default_error: Default error message if not provided in response

    Raises:
        RuntimeError: If response status is not "ok"
    """
    if resp.get("status") != "ok":
        raise RuntimeError(resp.get("error", default_error))


def _serialize_input(input_data: np.ndarray) -> Dict[str, Any]:
    """
    Serialize numpy array for transmission to worker.

    Args:
        input_data: Input numpy array

    Returns:
        Dictionary with serialized input data
    """
    return {
        "dtype": input_data.dtype.str,
        "shape": list(input_data.shape),
        "data": input_data.tobytes(),
    }


def _deserialize_outputs(outputs_data: List[Dict[str, Any]]) -> List[np.ndarray]:
    """
    Deserialize output data from worker.

    Args:
        outputs_data: List of serialized output dictionaries

    Returns:
        List of numpy arrays
    """
    outputs = []
    for item in outputs_data:
        dtype = np.dtype(item["dtype"])
        arr = np.frombuffer(item["data"], dtype=dtype).reshape(item["shape"])
        outputs.append(arr)
    return outputs


class WorkerClient:
    """Client handle to one TensorRT worker subprocess (lifecycle + IPC).

    Spawns/owns the worker process listening on ``port`` and proxies
    load-model/inference/details calls to it over the connection. Shared and
    cached across ModelManagers (a process singleton per port) — never closed
    per-ModelManager.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self._process: Optional[subprocess.Popen] = None
        self._conn: Optional[Any] = None
        self._lock = RLock()  # Reentrant: ensure_connected may be called while lock is held
        self._input_details: Optional[List[Dict[str, Any]]] = None
        self._output_details: Optional[List[Dict[str, Any]]] = None
        self._request_timeout = float(os.environ.get("WORKER_REQUEST_TIMEOUT_SEC", "8.0"))
        self._log_file: Optional[Any] = None
        # Last model successfully asked to load. A worker subprocess can be
        # (re)started transparently — lazily on first use, or by the retry path
        # after a comm error — and a fresh worker has NO model loaded. We
        # remember the path here so every (re)start re-loads it before serving
        # requests; otherwise the worker would answer "model not loaded" until
        # something explicitly reloaded it.
        self._model_path: Optional[str] = None

    def _start(self) -> None:
        """Start the worker process and establish connection."""
        if self._process is not None:
            return

        python_bin = sys.executable
        env = os.environ.copy()
        env["PYTHONPATH"] = "/app/inference-service"

        # Create log file for worker process
        log_file_path = f"/tmp/{WORKER_NAME}_worker_{self.port}.log"
        self._log_file = open(log_file_path, "w")

        logger.info("Starting TensorRT worker on port %s, logs: %s", self.port, log_file_path)

        self._process = subprocess.Popen(
            [
                python_bin,
                "-m",
                "api.runtime_management.worker_server",
                "--host",
                DEFAULT_HOST,
                "--port",
                str(self.port),
            ],
            env=env,
            start_new_session=True,
            stdout=self._log_file,
            stderr=self._log_file,
        )

        # Wait for worker to be ready
        self._wait_for_connection()

        # Self-heal: a freshly (re)started worker has no model loaded. If we had
        # one before this (re)start, re-load it now so a transparent restart
        # (lazy reconnect / retry-after-error) is invisible to callers instead
        # of surfacing as "model not loaded" on the next infer.
        if self._model_path is not None:
            self._reload_model_after_start()

    def _reload_model_after_start(self) -> None:
        """Re-issue the last ``load`` to a freshly started worker.

        Uses ``_send_and_receive`` directly (not ``_request``) to avoid
        re-entering the start/restart machinery from within ``_start``.
        Best-effort: a failure is logged and leaves the worker model-less, which
        the next request will report as usual rather than wedging the start.
        """
        try:
            resp = self._send_and_receive(
                {"cmd": "load", "model_path": self._model_path}
            )
            _validate_response(resp, "Failed to reload model after worker restart")
            self._input_details = resp.get("input_details")
            self._output_details = resp.get("output_details")
            logger.info(
                "Reloaded model on %s worker (port %s) after restart: %s",
                WORKER_NAME, self.port, self._model_path,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(
                "Failed to reload model on %s worker (port %s) after restart: %s",
                WORKER_NAME, self.port, e,
            )

    def _wait_for_connection(self, max_attempts: int = 50) -> None:
        """
        Wait for worker to accept connections.

        Args:
            max_attempts: Maximum number of connection attempts

        Raises:
            RuntimeError: If connection fails after max_attempts
        """
        for attempt in range(max_attempts):
            # Check if process died
            if self._process is not None and self._process.poll() is not None:
                # Process has exited, read log file for error details
                log_file_path = f"/tmp/{WORKER_NAME}_worker_{self.port}.log"
                error_msg = f"Worker process exited with code {self._process.returncode}"
                try:
                    if os.path.exists(log_file_path):
                        with open(log_file_path, "r") as f:
                            log_content = f.read()
                            if log_content:
                                error_msg += f"\nLog output:\n{log_content}"
                except Exception as e:
                    logger.error(f"{e} /nBypassing")
                    pass
                raise RuntimeError(f"Failed to start TensorRT worker: {error_msg}")

            try:
                self._conn = Client((DEFAULT_HOST, self.port), authkey=AUTH_KEY)
                return
            except ConnectionRefusedError:
                time.sleep(0.1)

        raise RuntimeError(f"Failed to connect to TensorRT worker on port {self.port}")

    def ensure_connected(self) -> None:
        """Ensure connection to worker is established (thread-safe)."""
        with self._lock:
            if self._conn is None:
                self._start()

    def _close_connection(self) -> None:
        """Close the connection to the worker."""
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError as e:
                logger.warning("Error closing connection: %s", e)
            finally:
                self._conn = None

    def _terminate_process(self, timeout: float = 2.0) -> None:
        """
        Terminate the worker process and wait for the port to be released.

        Args:
            timeout: Seconds to wait for graceful termination before killing
        """
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=timeout)
            except TimeoutExpired:
                self._process.kill()
                self._process.wait()
            except OSError as e:
                logger.warning("Error terminating process: %s", e)
                try:
                    self._process.kill()
                    self._process.wait()
                except OSError:
                    logger.exception("Failed to kill worker process")
            finally:
                self._process = None

        # Close log file
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError as e:
                logger.warning("Error closing log file: %s", e)
            finally:
                self._log_file = None

        # Wait for the OS to release the port before the caller tries to rebind
        self._wait_for_port_release()

    def _wait_for_port_release(self, max_wait: float = 5.0, interval: float = 0.1) -> None:
        """
        Poll until the worker port is no longer bound or max_wait is reached.

        Args:
            max_wait: Maximum seconds to wait
            interval: Polling interval in seconds
        """
        import socket
        deadline = time.monotonic() + max_wait
        while time.monotonic() < deadline:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    s.bind((DEFAULT_HOST, self.port))
                # Bind succeeded → port is free
                return
            except OSError:
                time.sleep(interval)
        logger.warning("Port %s may still be in use after %ss", self.port, max_wait)

    def _restart_worker(self) -> None:
        """Restart the worker process."""
        self._close_connection()
        self._terminate_process()

    def _send_and_receive(self, payload: Dict[str, Any], timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Send payload and receive response from worker.

        Args:
            payload: Request payload to send
            timeout: Response timeout in seconds (default: self._request_timeout)

        Returns:
            Response dictionary from worker

        Raises:
            TimeoutError: If worker doesn't respond within timeout
            RuntimeError: If response is invalid
        """
        assert self._conn is not None

        effective_timeout = timeout if timeout is not None else self._request_timeout
        self._conn.send(payload)
        if not self._conn.poll(effective_timeout):
            raise TimeoutError(
                f"TensorRT worker timeout after {effective_timeout:.1f}s"
            )

        response = self._conn.recv()
        if not isinstance(response, dict):
            raise RuntimeError("Invalid worker response")

        return response

    def _request(self, payload: Dict[str, Any], retry_on_fail: bool = True, timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Send request to worker with automatic retry on failure.

        Args:
            payload: Request payload
            retry_on_fail: Whether to retry once on failure
            timeout: Response timeout in seconds (default: self._request_timeout)

        Returns:
            Response dictionary from worker
        """
        with self._lock:
            self._start() if self._conn is None else None

            try:
                return self._send_and_receive(payload, timeout=timeout)
            except (OSError, TimeoutError, RuntimeError) as e:
                logger.warning("Worker communication error, restarting: %s", e)
                self._restart_worker()
                if retry_on_fail:
                    self._start()
                    return self._send_and_receive(payload, timeout=timeout)
                raise

    def load_model(self, model_path: str) -> None:
        """
        Load model in the worker process.

        If a model is already loaded (worker running), sends the new load
        command to the existing worker — no restart needed.  If the connection
        is broken for any reason, restarts the worker first.

        Args:
            model_path: Path to the model file
        """
        resp = self._request({"cmd": "load", "model_path": model_path})
        _validate_response(resp, "Failed to load model")
        # Remember the path only after a successful load so a later transparent
        # (re)start re-loads it. Setting it after avoids _start's self-heal
        # double-loading during this very call (the lazy start inside _request
        # would otherwise both reload and then load again).
        self._model_path = model_path
        self._input_details = resp.get("input_details")
        self._output_details = resp.get("output_details")

    def infer(self, input_data: np.ndarray) -> List[np.ndarray]:
        """
        Run inference on input data.

        Args:
            input_data: Input numpy array

        Returns:
            List of output numpy arrays
        """
        payload = {
            "cmd": "infer",
            "input": _serialize_input(input_data),
        }
        resp = self._request(payload)
        _validate_response(resp, "Inference failed")
        return _deserialize_outputs(resp.get("outputs", []))

    def build_engine(self, onnx_path: str, engine_path: str, workspace_mb: int = 256) -> None:
        """
        Build a TensorRT .engine from an .onnx file.

        Runs inside the worker process where TensorRTInterpreter is already
        initialized (CUDA context active via deserialize_cuda_engine), so
        _build_engine_from_onnx works without any extra CUDA setup.

        Args:
            onnx_path: Path to the ONNX model (already exported from .pt)
            engine_path: Destination path for the .engine file
            workspace_mb: TensorRT builder workspace size in MB
        """
        # Engine builds can take 10-30+ minutes on embedded hardware
        build_timeout = float(os.environ.get("TENSORRT_BUILD_TIMEOUT_SEC", "1800"))
        resp = self._request(
            {
                "cmd": "build_engine",
                "onnx_path": onnx_path,
                "engine_path": engine_path,
                "workspace_mb": workspace_mb,
            },
            retry_on_fail=False,
            timeout=build_timeout,
        )
        _validate_response(resp, "Engine build failed")

    def get_input_details(self) -> List[Dict[str, Any]]:
        """
        Get input tensor details.

        Returns:
            List of input tensor detail dictionaries

        Raises:
            RuntimeError: If model not loaded
        """
        if self._input_details is None:
            raise RuntimeError("Model not loaded")
        return self._input_details

    def get_output_details(self) -> List[Dict[str, Any]]:
        """
        Get output tensor details.

        Returns:
            List of output tensor detail dictionaries

        Raises:
            RuntimeError: If model not loaded
        """
        if self._output_details is None:
            raise RuntimeError("Model not loaded")
        return self._output_details

    def _send_close_command(self) -> None:
        """Send close command to worker process."""
        if self._conn is not None:
            try:
                self._conn.send({"cmd": "close"})
                if self._conn.poll(1.0):
                    self._conn.recv()
            except OSError as e:
                logger.warning("Error sending close command: %s", e)

    def close(self) -> None:
        """Close the worker client and terminate the worker process."""
        with self._lock:
            self._send_close_command()
            self._close_connection()
            self._terminate_process(timeout=5.0)


_client_cache: Dict[int, WorkerClient] = {}


def _get_worker_port() -> int:
    """Return the base IPC port for the TensorRT worker."""
    return int(os.environ.get("TENSORRT_WORKER_PORT", "5501"))


def get_worker_client(port: Optional[int] = None) -> WorkerClient:
    """Get or create a TensorRT worker client on a given port.

    Each port maps to its own worker subprocess (its own CUDA context / engine),
    enabling multiple inference contexts that run in parallel on the GPU. The
    default port comes from ``TENSORRT_WORKER_PORT``.
    """
    if port is None:
        port = _get_worker_port()

    if port in _client_cache:
        return _client_cache[port]

    client = WorkerClient(port)
    _client_cache[port] = client
    return client


def release_all_workers() -> None:
    """Terminate every cached worker subprocess, freeing its CUDA memory.

    Used by the training-service GPU handover (ManagementControl.ReleaseRuntime):
    the worker processes exit so the kernel reclaims their TensorRT contexts and
    engine memory. The cache entries are kept on purpose — each client remembers
    its ``_model_path`` and transparently restarts + reloads the engine on the
    next request, so resuming inference needs no special casing here.
    """
    for client in list(_client_cache.values()):
        try:
            client.close()
        except Exception as e:  # noqa: BLE001 - releasing must not wedge on one worker
            logger.warning("Failed to close worker on port %s: %s", client.port, e)
