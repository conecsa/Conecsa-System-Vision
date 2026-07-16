"""Model manager that wires the TensorRT runtime to the YOLO detector."""
import logging
import os
import queue
import threading
from typing import Any, Dict, List, Optional

# noinspection PyPackageRequirements
import numpy as np # Package is included on os build.

# noinspection PyPackageRequirements
import cv2 # Package is included on os build.

from .runtime_management import RuntimeFactory
from .runtime_management.base_runtime import Interpreter

logger = logging.getLogger(__name__)


class ModelManager:
    """Class to manage loading and execution of TensorRT models."""

    def __init__(self, config):
        self.config = config
        self.interpreter: Optional[Interpreter] = None
        self.input_details: List[Dict[str, Any]] = []
        self.output_details: List[Dict[str, Any]] = []
        self.input_size = 0
        self.acceleration_type = "GPU"
        self._inference_lock = threading.Lock()  # Lock to ensure thread-safe access

        # Optional pool of additional inference contexts (multi-context). Each
        # entry is an interpreter backed by its own worker subprocess / CUDA
        # context, so N pipeline threads calling run_inference run in parallel.
        # ``_pool`` stays None (single-context behaviour) unless TENSORRT_CONTEXTS>1.
        self._extra_interpreters = []
        self._pool = None

        self.runtime = RuntimeFactory.get_runtime_for_model(self.config.MODEL_PATH)
        self.runtime_api = self.runtime.name

        self._setup_interpreter()
        self._build_context_pool()
    
    def _setup_interpreter(self):
        """Create the TensorRT interpreter."""
        logger.info("Creating TensorRT interpreter...")
        interpreter = self.runtime.create_interpreter(self.config.MODEL_PATH)
        self.interpreter = interpreter
        logger.info(f"Model loaded successfully: {self.config.MODEL_PATH} with TensorRT")
        self._finalize_interpreter_setup(interpreter)

    def _finalize_interpreter_setup(self, interpreter: Interpreter):
        """Get input and output details and print model information."""
        self.input_details = interpreter.get_input_details()
        self.output_details = interpreter.get_output_details()
        self.input_size = self.input_details[0]['shape'][1]
        self._print_model_details()

    def _build_context_pool(self):
        """Spin up extra inference contexts when TENSORRT_CONTEXTS > 1.

        The primary interpreter (base port) plus N-1 extra interpreters (each its
        own worker subprocess on base_port+i) form a pool; ``run_inference`` draws
        a free context per call, so N concurrent callers infer in parallel on the
        GPU. Only the remote TensorRT runtime supports this; everything else keeps
        the single-context lock path. Best-effort: if an extra context fails to
        start we keep whatever we managed to create.
        """
        try:
            n = int(os.environ.get("TENSORRT_CONTEXTS", "1"))
        except ValueError:
            n = 1
        if n <= 1:
            return

        base = int(os.environ.get("TENSORRT_WORKER_PORT", "5501"))
        pool = queue.Queue()
        pool.put(self.interpreter)  # primary context (base port)
        for i in range(1, n):
            port = base + i
            try:
                interp = self.runtime.create_interpreter_on_port(self.config.MODEL_PATH, port)
                self._extra_interpreters.append(interp)
                pool.put(interp)
                logger.info("[ModelManager] extra TensorRT context %d ready on port %d", i, port)
            except Exception as ex:  # noqa: BLE001
                logger.warning("[ModelManager] extra context on port %d failed: %s", port, ex)

        if self._extra_interpreters:
            self._pool = pool
            logger.info("[ModelManager] inference pool active: %d contexts", pool.qsize())

    def __del__(self):
        """Destructor to properly clean up resources."""
        # noinspection PyBroadException
        try:
            # Drop references to the extra inference contexts, but DO NOT close
            # their worker clients here. Those clients are process-global
            # singletons cached in worker_client._client_cache and shared across
            # ModelManager instances — a model swap re-issues `load` to the same
            # workers rather than spawning new ones. Closing them in this
            # destructor means a *previous* ModelManager being garbage-collected
            # after a swap would terminate the worker the *current* ModelManager
            # is using, leaving that inference lane answering "model not loaded"
            # (throughput then halves). The workers live for the process and are
            # reloaded on the next swap; mirror how the primary context (5501) is
            # already only dereferenced, never closed, here.
            self._extra_interpreters = []
            self._pool = None

            # Clean up interpreter
            if hasattr(self, 'interpreter'):
                self.interpreter = None
        except Exception:  # noqa: E722
            pass  # Ignore all errors during cleanup

    def _print_model_details(self):
        """Log model structure details for debugging."""
        logger.debug(f"Number of outputs: {len(self.output_details)}")
        for i, detail in enumerate(self.output_details):
            logger.debug(f"Output {i}: name='{detail['name']}', shape={detail['shape']}, dtype={detail['dtype']}")
    
    def preprocess_image(self, image_original):
        """
        Preprocesses the image for inference.

        Args:
            image_original: Original OpenCV image

        Returns:
            tuple: (processed image, scale)
        """
        
        height1 = image_original.shape[0]
        width1 = image_original.shape[1]
        
        # Check expected input shape to determine format and actual input size
        expected_shape = self.input_details[0]['shape']
        
        # Channels-first (ONNX/TensorRT) vs channels-last layout.
        is_channels_first = (len(expected_shape) == 4 and expected_shape[1] == 3)

        if is_channels_first:
            actual_input_size = expected_shape[2]
        else:
            actual_input_size = self.input_size
        
        
        # Resize image to required size for inference
        image = cv2.resize(image_original,
                          (actual_input_size, int(actual_input_size * height1 / width1)),
                          interpolation=cv2.INTER_NEAREST)
        
        height2 = image.shape[0]
        scale = height1 / height2
        border_top = int((actual_input_size - height2) / 2)
        border_bottom = actual_input_size - height2 - border_top
        
        image = cv2.copyMakeBorder(image,
                                  border_top,
                                  border_bottom,
                                  0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        
        
        # Convert BGR to RGB
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        if is_channels_first:
            input_tensor = np.transpose(image_rgb, (2, 0, 1))
            input_tensor = np.expand_dims(input_tensor, axis=0)
            if self.input_details[0]['dtype'] == np.float32:
                input_tensor = input_tensor.astype(np.float32) / 255.0
            else:
                input_tensor = input_tensor.astype(np.uint8)
        else:
            input_tensor = np.array([image_rgb], dtype=np.uint8)
            if self.input_details[0]['dtype'] == np.float32:
                input_tensor = (np.float32(input_tensor) - 127.5) / 127.5

        return input_tensor, scale, border_top, actual_input_size
    
    def run_inference(self, input_tensor):
        """
        Runs inference.
        Thread-safe using internal lock.

        Args:
            input_tensor: Preprocessed input tensor

        Returns:
            tuple: (output data, inference time)
        """
        # Multi-context: draw a free context from the pool (each is backed by its
        # own worker subprocess, so N concurrent callers run in parallel). The
        # queue itself guarantees one caller per interpreter at a time.
        if self._pool is not None:
            interpreter = self._pool.get()
            try:
                return self._invoke(interpreter, input_tensor)
            finally:
                self._pool.put(interpreter)

        # Single-context path. Serialize access to the interpreter; the
        # multi-context path above uses one worker subprocess per concurrent
        # lane instead.
        interpreter = self.interpreter
        if interpreter is None:
            raise RuntimeError("Model not loaded: interpreter is unavailable")
        with self._inference_lock:
            return self._invoke(interpreter, input_tensor)

    def _invoke(self, interpreter: Interpreter, input_tensor):
        """Run one inference on ``interpreter``. Returns ``(output_data, seconds)``."""
        from time import time

        # IMPORTANT: Make a copy of input tensor to avoid internal references.
        input_copy = np.copy(input_tensor)
        interpreter.set_tensor(self.input_details[0]['index'], input_copy)

        t1 = time()
        try:
            interpreter.invoke()
            t2 = time()
        except RuntimeError as e:
            logger.error(f"Inference failed: {e}")
            raise e

        output_data = np.array(interpreter.get_tensor(self.output_details[0]['index']))

        # Explicitly release references before returning
        del input_copy

        return output_data, t2 - t1
