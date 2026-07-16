"""
TensorRT runtime implementation using native Python API.
"""
import logging

from .base_runtime import BaseRuntime
from api.runtime_management._trt_engine_builder import ensure_cudla_compat
from .tensorrt_interpreter import TensorRTInterpreter

logger = logging.getLogger(__name__)


class TensorRTRuntime(BaseRuntime):
    """TensorRT runtime implementation using native Python API."""

    def __init__(self) -> None:
        """Initialize TensorRT runtime."""
        super().__init__("TensorRT")

    def _check_availability(self) -> None:
        """Check if TensorRT is available."""
        try:
            ensure_cudla_compat()

            # The following packages are included on os build.

            # noinspection PyPackageRequirements
            import tensorrt as trt  # type: ignore
            # noinspection PyPackageRequirements
            import pycuda.driver as cuda  # type: ignore
            # noinspection PyPackageRequirements
            import pycuda.autoinit as _  # type: ignore # noqa: F401 Initializes CUDA context for this process

            self._runtime_module = trt  # type: ignore
            self._available = True
            logger.info("%s runtime is available", self.name)
            logger.info("  TensorRT version: %s", trt.__version__)

            # Check CUDA availability
            try:
                cuda.init()  # type: ignore
                device_count = cuda.Device.count()  # type: ignore
                if device_count > 0:
                    device = cuda.Device(0)  # type: ignore
                    logger.info("  CUDA device: %s (%s)", device.name(), device.compute_capability())  # type: ignore
                else:
                    logger.warning("  No CUDA devices found")
            except Exception as e:
                logger.warning("  CUDA check failed: %s", e)

        except ImportError as e:
            logger.error("%s runtime is not available: %s", self.name, e)
            logger.info("  Install with: pip install tensorrt pycuda")
            self._available = False

    def create_interpreter(self, model_path: str):
        """
        Create and initialize a TensorRT interpreter.

        Args:
            model_path: Path to the TensorRT engine (.engine/.plan) or ONNX model (.onnx)

        Returns:
            TensorRTInterpreter instance
        """
        if not self._available or self._runtime_module is None:
            raise RuntimeError(f"{self.name} runtime is not available")

        interpreter = TensorRTInterpreter(model_path, use_cuda=True)
        interpreter.allocate_tensors()

        return interpreter
