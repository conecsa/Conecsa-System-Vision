"""
TensorRT interpreter: a native Python-API wrapper exposing the small
interpreter surface ModelManager uses.

Split out from tensorrt_runtime.py so the runtime registration
(``TensorRTRuntime``) stays separate from the per-model interpreter that
owns the engine, execution context and CUDA buffers.
"""
import gc
import logging
import os

# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

from typing import Optional, Any, Dict, List
from .base_runtime import create_tensor_info
from api.runtime_management._trt_engine_builder import (
    ensure_cudla_compat,
    build_engine as build_engine_from_onnx,
)

logger = logging.getLogger(__name__)


class TensorRTInterpreter:
    """
    TensorRT interpreter with the small interpreter interface ModelManager uses.
    Provides seamless integration with existing model management code.
    """

    def __init__(self, model_path: str, use_cuda: bool = True):
        """
        Initialize TensorRT interpreter.

        Args:
            model_path: Path to the TensorRT engine file (.engine or .plan) or ONNX model
            use_cuda: Whether to use CUDA for inference (default: True)
        """
        ensure_cudla_compat()
        # noinspection PyPackageRequirements
        import tensorrt as trt  # type: ignore  # Package is included on os build.
        # noinspection PyPackageRequirements
        import pycuda.driver as cuda  # type: ignore  # Package is included on os build.

        self.trt = trt  # type: ignore
        self.cuda = cuda  # type: ignore
        self.model_path = model_path
        self.use_cuda = use_cuda

        # TensorRT objects. Annotated as Any because trt is imported lazily
        # (inside __init__), so the concrete trt.Runtime/ICudaEngine/
        # IExecutionContext types aren't in scope at class level; without this
        # the checker infers them as exactly None and flags every method call.
        self.logger = trt.Logger(trt.Logger.WARNING)  # type: ignore
        self.runtime: Any = None
        self.engine: Any = None
        self.context: Any = None

        # Tensor information
        self._input_details: List[Dict[str, Any]] = []
        self._output_details: List[Dict[str, Any]] = []

        # CUDA memory buffers
        self._input_buffers: List[Any] = []
        self._output_buffers: List[Any] = []
        self._bindings: List[int] = []

        # Host memory for input/output
        self._input_host: List[np.ndarray] = []
        self._output_host: List[np.ndarray] = []

        # Load the engine
        self._load_engine()

    def _load_engine(self):
        """Load TensorRT engine from file."""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(f"TensorRT engine not found: {self.model_path}")

        model_ext = os.path.splitext(self.model_path)[1].lower()

        if model_ext in ['.engine', '.plan']:
            self._load_engine_file()
        elif model_ext == '.onnx':
            self.build_engine_from_onnx()
        else:
            raise ValueError(
                f"Unsupported model format: {model_ext}. "
                f"Supported formats: .engine, .plan, .onnx"
            )

    def _create_runtime(self):
        """Create TensorRT runtime if not already created."""
        if self.runtime is None:
            self.runtime = self.trt.Runtime(self.logger)  # type: ignore

    def _load_engine_file(self):
        """Load pre-built TensorRT engine from .engine or .plan file."""
        self._create_runtime()

        with open(self.model_path, 'rb') as f:
            engine_data = f.read()
            self.engine = self.runtime.deserialize_cuda_engine(engine_data)

        if self.engine is None:
            try_rebuild = os.environ.get('TENSORRT_AUTO_REBUILD_ENGINE', '1') == '1'
            sibling_onnx = os.path.splitext(self.model_path)[0] + '.onnx'

            if try_rebuild and os.path.exists(sibling_onnx):
                self.build_engine_from_onnx(onnx_path=sibling_onnx, engine_cache_path=self.model_path)
                return

            raise RuntimeError(
                "Failed to load TensorRT engine (serialization/version mismatch). "
                "Re-export the engine on this same device/runtime, or provide a sibling .onnx "
                "with the same filename base and set TENSORRT_AUTO_REBUILD_ENGINE=1."
            )

        self._create_context_and_setup()

    def _create_context_and_setup(self):
        """Create execution context and setup tensors."""
        self.context = self.engine.create_execution_context()
        self._setup_tensors()

    def build_engine_from_onnx(self, onnx_path: Optional[str] = None, engine_cache_path: Optional[str] = None):
        """Build TensorRT engine from ONNX model and load it into this interpreter."""
        onnx_path = onnx_path or self.model_path
        if engine_cache_path is None:
            engine_cache_path = onnx_path.replace('.onnx', '.engine')

        logger.info("Building TensorRT engine from ONNX: %s", onnx_path)
        build_engine_from_onnx(onnx_path, engine_cache_path)

        # Teardown previous engine + context before deserializing the new one.
        # Without this, pycuda mem_alloc'd device buffers and the old execution
        # context stay reachable through stale list entries (see _setup_tensors)
        # and never get released.
        if self.context is not None:
            del self.context
            self.context = None
        if self.engine is not None:
            del self.engine
            self.engine = None
        gc.collect()

        # Load the freshly built engine
        self._create_runtime()
        if self.runtime is None:
            raise RuntimeError("Failed to create TensorRT runtime")
        with open(engine_cache_path, 'rb') as f:
            self.engine = self.runtime.deserialize_cuda_engine(f.read())
        if self.engine is None:
            raise RuntimeError("Failed to deserialize the newly built TensorRT engine")
        self._create_context_and_setup()

    def _get_numpy_dtype(self, trt_dtype) -> type:
        """
        Convert TensorRT dtype to numpy dtype.

        Args:
            trt_dtype: TensorRT DataType

        Returns:
            Numpy dtype
        """
        dtype_map = {
            self.trt.DataType.FLOAT: np.float32,  # type: ignore
            self.trt.DataType.HALF: np.float16,  # type: ignore
            self.trt.DataType.INT8: np.int8,  # type: ignore
            self.trt.DataType.INT32: np.int32,  # type: ignore
            self.trt.DataType.BOOL: np.bool_,  # type: ignore
        }
        return dtype_map.get(trt_dtype, np.float32)

    def _allocate_tensor_memory(self, tensor_size: int):
        """
        Allocate CUDA device memory for a tensor.

        Args:
            tensor_size: Size of the tensor in bytes

        Returns:
            CUDA device memory pointer or None
        """
        if self.use_cuda:
            device_mem = self.cuda.mem_alloc(tensor_size)  # type: ignore
            self._bindings.append(int(device_mem))
            return device_mem
        return None

    def _setup_tensors(self):
        """Setup input/output tensors and allocate CUDA memory."""
        # Reset binding/buffer lists. Without this, a rebuild_engine_from_onnx
        # call on an existing interpreter would APPEND new pycuda mem_alloc()
        # handles + numpy buffers to the lists, leaking the previous engine's
        # device memory every time (root cause of the TRT worker process
        # reaching VmPeak 10.6 GB on the Yocto host).
        self._bindings.clear()
        self._input_buffers.clear()
        self._output_buffers.clear()
        self._input_host.clear()
        self._output_host.clear()
        self._input_details.clear()
        self._output_details.clear()

        input_idx = 0
        output_idx = 0

        for i in range(self.engine.num_io_tensors):
            tensor_name = self.engine.get_tensor_name(i)
            tensor_shape = self.engine.get_tensor_shape(tensor_name)
            tensor_dtype = self.engine.get_tensor_dtype(tensor_name)

            # Convert TensorRT dtype to numpy dtype
            np_dtype = self._get_numpy_dtype(tensor_dtype)

            # Calculate tensor size
            tensor_size = int(np.prod(tensor_shape)) * int(np_dtype().itemsize)

            # Allocate device memory
            device_mem = self._allocate_tensor_memory(tensor_size)

            # Allocate host memory
            host_mem = np.empty(tensor_shape, dtype=np_dtype)

            # Classify as input or output and create tensor info
            is_input = self.engine.get_tensor_mode(tensor_name) == self.trt.TensorIOMode.INPUT  # type: ignore

            if is_input:
                tensor_info = create_tensor_info(tensor_name, input_idx, list(tensor_shape), np_dtype)
                self._input_details.append(tensor_info)
                self._input_buffers.append(device_mem)
                self._input_host.append(host_mem)
                input_idx += 1
            else:
                tensor_info = create_tensor_info(tensor_name, output_idx, list(tensor_shape), np_dtype)
                self._output_details.append(tensor_info)
                self._output_buffers.append(device_mem)
                self._output_host.append(host_mem)
                output_idx += 1

    def allocate_tensors(self):
        """Allocate tensors (compatibility method, already handled in _setup_tensors)."""
        pass

    def get_input_details(self):
        """Get input tensor details."""
        return self._input_details

    def get_output_details(self):
        """Get output tensor details."""
        return self._output_details

    def set_tensor(self, tensor_index: int, value: np.ndarray):
        """
        Set input tensor value.

        Args:
            tensor_index: Index of the tensor
            value: Numpy array with input data
        """
        if tensor_index >= len(self._input_details):
            raise IndexError(f"Input tensor index {tensor_index} out of range")

        expected_shape = self._input_details[tensor_index]['shape']
        expected_dtype = self._input_details[tensor_index]['dtype']

        # Ensure correct shape and dtype
        value = np.ascontiguousarray(value.reshape(expected_shape).astype(expected_dtype))

        # Copy to host memory
        self._input_host[tensor_index][:] = value

        # Copy to device memory if using CUDA
        if self.use_cuda and self._input_buffers[tensor_index] is not None:
            self.cuda.memcpy_htod(self._input_buffers[tensor_index], value)  # type: ignore

    def get_tensor(self, tensor_index: int) -> np.ndarray:
        """
        Get output tensor value.

        Args:
            tensor_index: Index of the tensor

        Returns:
            Numpy array with output data
        """
        if tensor_index >= len(self._output_details):
            raise IndexError(f"Output tensor index {tensor_index} out of range")

        return self._output_host[tensor_index]

    def _set_tensor_bindings(self):
        """Set input and output tensor bindings for TensorRT context."""
        # Set input bindings
        for i, detail in enumerate(self._input_details):
            tensor_name = detail['name']
            address = self._bindings[i] if self.use_cuda else self._input_host[i].ctypes.data
            self.context.set_tensor_address(tensor_name, address)

        # Set output bindings
        for i, detail in enumerate(self._output_details):
            tensor_name = detail['name']
            binding_idx = len(self._input_details) + i
            address = self._bindings[binding_idx] if self.use_cuda else self._output_host[i].ctypes.data
            self.context.set_tensor_address(tensor_name, address)

    def _copy_outputs_to_host(self):
        """Copy output tensors from device to host memory if using CUDA."""
        if self.use_cuda:
            for i, output_buffer in enumerate(self._output_buffers):
                if output_buffer is not None:
                    self.cuda.memcpy_dtoh(self._output_host[i], output_buffer)  # type: ignore

    def invoke(self):
        """Run inference using TensorRT."""
        if self.context is None:
            raise RuntimeError("TensorRT context not initialized")

        # Set tensor bindings
        self._set_tensor_bindings()

        # Execute inference
        self.context.execute_async_v3(stream_handle=0)

        # Copy outputs from device to host
        self._copy_outputs_to_host()

    def close(self):
        """
        Explicit teardown. Releases TRT context, engine, runtime, pycuda
        device buffers and host numpy buffers in the correct order.

        Callers (worker_server._handle_load_command) MUST invoke this
        before dropping the reference. __del__ alone is unreliable because
        TRT engine <-> context <-> bindings form reference cycles that
        defeat CPython refcount-based cleanup.
        """
        # Release host numpy buffers / device handle lists first so they
        # drop their references to the pycuda DeviceAllocation objects.
        if hasattr(self, '_input_host'):
            self._input_host.clear()
        if hasattr(self, '_output_host'):
            self._output_host.clear()
        if hasattr(self, '_input_buffers'):
            self._input_buffers.clear()
        if hasattr(self, '_output_buffers'):
            self._output_buffers.clear()
        if hasattr(self, '_bindings'):
            self._bindings.clear()
        if hasattr(self, '_input_details'):
            self._input_details.clear()
        if hasattr(self, '_output_details'):
            self._output_details.clear()

        # Order matters: context depends on engine, engine on runtime.
        if getattr(self, 'context', None) is not None:
            del self.context
            self.context = None
        if getattr(self, 'engine', None) is not None:
            del self.engine
            self.engine = None
        if getattr(self, 'runtime', None) is not None:
            del self.runtime
            self.runtime = None

        gc.collect()

    def __del__(self):
        # Best-effort fallback; main path is the explicit close().
        try:
            self.close()
        except Exception:
            logger.debug("Suppressed exception during TensorRTInterpreter.__del__ cleanup", exc_info=True)
