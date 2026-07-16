"""
Runtime factory for creating and managing the TensorRT runtime instance.
"""
import logging
import os
from typing import Optional
from .base_runtime import BaseRuntime
from .remote_runtime import RemoteRuntime

logger = logging.getLogger(__name__)


class RuntimeFactory:
    """Factory for creating and managing the TensorRT runtime instance."""

    _runtime: Optional[BaseRuntime] = None
    _initialized: bool = False

    @classmethod
    def _initialize_runtime(cls):
        """Initialize and register the TensorRT runtime if it is available."""
        try:
            runtime = RemoteRuntime("TensorRT")
            if runtime.available:
                cls._runtime = runtime
        except Exception as e:
            logger.error("Failed to initialize TensorRT runtime: %s", e)

    @classmethod
    def _initialize_runtimes(cls):
        """Initialize the TensorRT runtime lazily."""
        if cls._initialized:
            return
        logger.info("Initializing TensorRT runtime...")
        cls._initialize_runtime()
        cls._initialized = True
        logger.info("TensorRT runtime available: %s", cls._runtime is not None)

    @classmethod
    def get_runtime_for_model(cls, model_path: str) -> BaseRuntime:
        """
        Get the runtime instance for a given model path. Only TensorRT-compatible
        formats are accepted (`.engine`, `.plan`, `.onnx`).
        """
        cls._initialize_runtimes()

        if not cls.is_supported_model(model_path):
            raise RuntimeError(
                f"Unsupported model format '{os.path.splitext(model_path)[1]}'. "
                "Only .engine, .plan and .onnx are supported."
            )

        if cls._runtime is None:
            raise RuntimeError(
                "TensorRT runtime is not available on this system. "
                "TensorRT is required for .engine/.plan/.onnx model files."
            )
        return cls._runtime

    @classmethod
    def is_supported_model(cls, model_path: str) -> bool:
        """Return True for TensorRT-compatible model extensions."""
        ext = os.path.splitext(model_path)[1].lower()
        return ext in ('.engine', '.plan', '.onnx')
