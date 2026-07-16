"""Remote runtime proxy backed by the TensorRT worker subprocess."""
from typing import Dict, List, Optional

import numpy as np

from .base_runtime import BaseRuntime
from .worker_client import get_worker_client


class RemoteInterpreter:
    """TFLite-style interpreter facade over a TensorRT worker subprocess.

    Presents the same ``set_tensor``/``invoke``/``get_tensor`` surface the
    detector expects, while the actual inference runs in a separate worker
    process (so the heavy CUDA context lives off the main process).
    """

    def __init__(self, model_path: str, port: Optional[int] = None) -> None:
        self._client = get_worker_client(port)
        self._client.load_model(model_path)
        self._input_details = self._client.get_input_details()
        self._output_details = self._client.get_output_details()
        self._input_data: Optional[np.ndarray] = None
        self._output_data: List[np.ndarray] = []
        # Map raw tensor index → position in _output_data list
        self._output_index_map: Dict[int, int] = {
            detail['index']: pos
            for pos, detail in enumerate(self._output_details)
        }

    def allocate_tensors(self) -> None:
        """No-op (the worker owns tensor allocation); kept for API parity."""
        pass

    def get_input_details(self):
        """Return the model's input tensor details (from the worker)."""
        return self._input_details

    def get_output_details(self):
        """Return the model's output tensor details (from the worker)."""
        return self._output_details

    def set_tensor(self, tensor_index: int, value: np.ndarray) -> None:
        """Stage the single input tensor (only index 0 is supported)."""
        if tensor_index != 0:
            raise IndexError("Only single-input models are supported")
        self._input_data = np.ascontiguousarray(value)

    def invoke(self) -> None:
        """Run inference in the worker on the staged input."""
        if self._input_data is None:
            raise RuntimeError("Input data not set. Call set_tensor() first.")
        self._output_data = self._client.infer(self._input_data)

    def get_tensor(self, tensor_index: int) -> np.ndarray:
        """Get output tensor by its sequential index from the worker."""
        pos = self._output_index_map.get(tensor_index)
        if pos is not None:
            if pos >= len(self._output_data):
                raise IndexError(f"Output tensor index {tensor_index} out of range")
            return self._output_data[pos]

        if tensor_index >= len(self._output_data):
            raise IndexError(f"Output tensor index {tensor_index} out of range")
        return self._output_data[tensor_index]


class RemoteRuntime(BaseRuntime):
    """BaseRuntime that creates :class:`RemoteInterpreter`s backed by workers."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_availability(self) -> None:
        """Mark the runtime available iff a worker client can be obtained."""
        # If the worker can be started, we consider the runtime available.
        get_worker_client()
        self._available = True

    def create_interpreter(self, model_path: str):
        """Create a worker-backed interpreter for *model_path*."""
        if not self._available:
            raise RuntimeError(f"{self.name} runtime is not available")
        return RemoteInterpreter(model_path)

    def create_interpreter_on_port(self, model_path: str, port: int):
        """Create an interpreter backed by a dedicated worker context on ``port``.

        Used to spin up additional TensorRT contexts (one worker subprocess per
        port) so inference can run in parallel across them.
        """
        if not self._available:
            raise RuntimeError(f"{self.name} runtime is not available")
        return RemoteInterpreter(model_path, port)
