"""
Base runtime interface for model execution.
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Any, Dict, Protocol
import numpy as np


class Interpreter(Protocol):
    """TFLite-style interpreter surface shared by all runtime backends.

    Method bodies use ``...`` (not ``pass``) so the type checker treats them
    as stubs; otherwise it flags the typed methods for falling through without
    returning their declared value.
    """

    def allocate_tensors(self) -> None:
        ...

    def get_input_details(self) -> List[Dict[str, Any]]:
        ...

    def get_output_details(self) -> List[Dict[str, Any]]:
        ...

    def set_tensor(self, tensor_index: int, value: np.ndarray) -> None:
        ...

    def get_tensor(self, tensor_index: int) -> np.ndarray:
        ...

    def invoke(self) -> None:
        ...


def create_tensor_info(name: str, index: int, shape: List[int], dtype: type = np.float32) -> Dict[str, Any]:
    """
    Create an interpreter-compatible tensor info dictionary.

    Args:
        name: Tensor name
        index: Tensor index
        shape: Tensor shape
        dtype: Numpy dtype (default: np.float32)

    Returns:
        Tensor info dictionary
    """
    return {
        'name': name,
        'index': index,
        'shape': shape,
        'dtype': dtype,
        'quantization': (0.0, 0),
        'quantization_parameters': {'scales': np.array([]), 'zero_points': np.array([])},
        'sparsity_parameters': {}
    }


class BaseRuntime(ABC):
    """Abstract base class for runtime implementations."""

    def __init__(self, name: str) -> None:
        """
        Initialize the runtime.

        Args:
            name: Runtime name.
        """
        self.name = name
        self._available = False
        self._runtime_module: Optional[Any] = None
        self._check_availability()
        if not self._available:
            raise RuntimeError(f"{self.name} runtime is not available on this system")

    @abstractmethod
    def _check_availability(self) -> None:
        """Check if the runtime is available on the system."""
        pass

    @property
    def available(self) -> bool:
        """Returns whether this runtime is available."""
        return self._available

    @abstractmethod
    def create_interpreter(self, model_path: str) -> "Interpreter":
        """
        Create and allocate an interpreter.

        Args:
            model_path: Path to the model file.
        Returns:
            Initialized interpreter instance
        """
        pass

    def create_interpreter_on_port(self, model_path: str, port: int) -> "Interpreter":
        """
        Create an interpreter backed by a dedicated inference context on ``port``.

        Optional capability: only worker-backed runtimes can host more than one
        context. Callers building a multi-context pool treat the failure as
        non-fatal and fall back to the single-context path.

        Args:
            model_path: Path to the model file.
            port: Port of the worker hosting this context.
        Returns:
            Initialized interpreter instance
        """
        raise NotImplementedError(f"{self.name} runtime hosts a single inference context")

