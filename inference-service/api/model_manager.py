"""Model manager that wires the TensorRT runtime to the YOLO detector."""
import logging
import os
import queue
import threading
from typing import Any, Dict, List, NamedTuple, Optional

# noinspection PyPackageRequirements
import cv2  # Package is included on os build.

# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

from .runtime_management import RuntimeFactory
from .runtime_management.base_runtime import Interpreter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Preprocessing helpers (pure functions, host-testable without TensorRT)
# ---------------------------------------------------------------------------

# INFER_RESIZE_INTERP values -> OpenCV interpolation flags.
_RESIZE_INTERP_BY_NAME = {
    "nearest": cv2.INTER_NEAREST,
    "linear": cv2.INTER_LINEAR,
    "area": cv2.INTER_AREA,
}
DEFAULT_LETTERBOX_PAD = 0
DEFAULT_RESIZE_INTERP = "nearest"


def letterbox_pad_from_env() -> int:
    """Letterbox pad value from ``INFER_LETTERBOX_PAD`` (0..255, default 0 = black).

    Ultralytics trains and validates with gray (114) padding; ``0`` is the
    value the deployed engines are validated with. Out-of-range or
    non-numeric values fall back to the default.
    """
    raw = os.environ.get("INFER_LETTERBOX_PAD", str(DEFAULT_LETTERBOX_PAD)).strip()
    try:
        value = int(raw)
    except ValueError:
        logger.warning("INFER_LETTERBOX_PAD=%r is not an int; using %d", raw, DEFAULT_LETTERBOX_PAD)
        return DEFAULT_LETTERBOX_PAD
    if not 0 <= value <= 255:
        logger.warning("INFER_LETTERBOX_PAD=%d out of 0..255; using %d", value, DEFAULT_LETTERBOX_PAD)
        return DEFAULT_LETTERBOX_PAD
    return value


def resize_interp_from_env() -> int:
    """OpenCV interpolation flag from ``INFER_RESIZE_INTERP``.

    Accepts ``nearest`` (default), ``linear`` (what the
    ultralytics loader/LetterBox use) and ``area`` (anti-aliased downscale).
    Unknown names fall back to ``nearest``.
    """
    name = os.environ.get("INFER_RESIZE_INTERP", DEFAULT_RESIZE_INTERP).strip().lower()
    flag = _RESIZE_INTERP_BY_NAME.get(name)
    if flag is None:
        logger.warning("INFER_RESIZE_INTERP=%r unknown; using %s", name, DEFAULT_RESIZE_INTERP)
        return _RESIZE_INTERP_BY_NAME[DEFAULT_RESIZE_INTERP]
    return flag


# ---------------------------------------------------------------------------
# SAHI-style tiled inference (TILING_* knobs; default grid, tile = the
# frame's short side, so K=2 on any 16:9 camera)
# ---------------------------------------------------------------------------

_TILING_MODES = ("off", "grid")
DEFAULT_TILING_MODE = "grid"
DEFAULT_TILING_TILE = "auto"
DEFAULT_TILING_OVERLAP = 0.2


def tiling_mode_from_env() -> str:
    """Tiled-inference mode from ``TILING_MODE`` (``off`` | ``grid``).

    ``grid`` (default) slices the decoded frame into overlapping square
    tiles (``TILING_TILE`` side, ``TILING_OVERLAP`` fraction), runs one
    inference per tile and merges the shifted boxes, so a small object reaches
    the model at (close to) native scale instead of the full-frame downscale.
    With the default tile (the frame's short side) any 16:9 camera yields two
    columns (K=2), which the Orin Nano runs at camera rate with two lanes for
    the same memory and power as a single inference; a third, full-frame tile
    (K=3) falls below the 25 fps floor and is not offered. ``off`` keeps the
    single full-frame letterboxed inference (for models trained on whole
    frames). Unknown values fall back to the default.
    """
    raw = os.environ.get("TILING_MODE", DEFAULT_TILING_MODE).strip().lower()
    if raw not in _TILING_MODES:
        logger.warning("TILING_MODE=%r unknown %s; using %r", raw, _TILING_MODES, DEFAULT_TILING_MODE)
        return DEFAULT_TILING_MODE
    return raw


def tiling_tile_from_env() -> Optional[int]:
    """Square tile side from ``TILING_TILE``: ``auto`` (default, ``None``) or pixels.

    ``auto`` resolves per frame to the frame's short side
    (``conecsa_common.tiling.auto_tile``): the grid then degenerates to one
    row of columns whose count depends only on the aspect ratio, so the same
    setting is right for any camera the device is fitted with, and the model
    sees crops resized to its input (short side / engine input: 0.89x native
    object scale for a 640 engine on a 720-high frame, 0.59x on a 1080-high
    one). A pixel value pins the side instead (and must
    then match the ``TRAIN_TILE`` the model was trained with). Non-positive
    or non-numeric values fall back to ``auto``.
    """
    raw = os.environ.get("TILING_TILE", DEFAULT_TILING_TILE).strip().lower()
    if raw in ("", "auto"):
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("TILING_TILE=%r is neither 'auto' nor an int; using auto", raw)
        return None
    if value <= 0:
        logger.warning("TILING_TILE=%d must be positive; using auto", value)
        return None
    return value


def tiling_overlap_from_env() -> float:
    """Tile overlap fraction from ``TILING_OVERLAP`` (``0 <= f < 1``, default 0.2).

    The overlap band must exceed the largest object the tiles are meant to
    catch, or an object on the seam is cut in both tiles and merged badly.
    Invalid values fall back to the default.
    """
    raw = os.environ.get("TILING_OVERLAP", str(DEFAULT_TILING_OVERLAP)).strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning("TILING_OVERLAP=%r is not a number; using %s", raw, DEFAULT_TILING_OVERLAP)
        return DEFAULT_TILING_OVERLAP
    if not 0.0 <= value < 1.0:
        logger.warning("TILING_OVERLAP=%s out of [0, 1); using %s", value, DEFAULT_TILING_OVERLAP)
        return DEFAULT_TILING_OVERLAP
    return value


class TileMeta(NamedTuple):
    """Mapping data for one preprocessed tile (or the full frame).

    ``scale``/``border_top``/``input_size`` have the same meaning as the
    ``preprocess_image`` return values, computed against the crop;
    ``ox``/``oy`` are the tile origin in frame pixels (0 for the full frame)
    and ``width``/``height`` the crop size the detector decodes corners
    against before shifting them into frame space.
    """

    scale: float
    border_top: int
    input_size: int
    ox: int
    oy: int
    width: int
    height: int


def input_size_from_shape(shape) -> int:
    """Spatial input size (S) of a ``[1, 3, S, S]`` (NCHW) or ``[1, S, S, 3]`` (NHWC) shape.

    TensorRT engines exported from ONNX are channels-first, so ``shape[1]`` is
    the channel count (3), not the size; picking it would report an input size
    of 3 for every model.
    """
    if len(shape) == 4 and shape[1] == 3:
        return int(shape[2])
    return int(shape[1])


def letterbox_to_square(image_bgr, size: int, pad_value: int = DEFAULT_LETTERBOX_PAD,
                        interp: int = cv2.INTER_NEAREST):
    """Resize ``image_bgr`` so its width fills ``size`` and pad the height to ``size``.

    Only the Y axis is letterboxed (the camera frames are wider than tall):
    width is scaled to exactly ``size``, the resized height is centred between
    equal (±1 px) constant-colour bands. Returns ``(image, scale, border_top)``
    where ``scale = original_h / resized_h`` and ``border_top`` is the number of
    pad rows above the image, both consumed by the detector to map model-input
    coordinates back to the frame.
    """
    height1, width1 = image_bgr.shape[:2]
    resized_h = int(size * height1 / width1)
    image = cv2.resize(image_bgr, (size, resized_h), interpolation=interp)

    height2 = image.shape[0]
    scale = height1 / height2
    border_top = int((size - height2) / 2)
    border_bottom = size - height2 - border_top

    image = cv2.copyMakeBorder(image, border_top, border_bottom, 0, 0,
                               cv2.BORDER_CONSTANT,
                               value=(pad_value, pad_value, pad_value))
    return image, scale, border_top


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

        self._configure_preprocessing()

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
        self.input_size = input_size_from_shape(self.input_details[0]['shape'])
        self._print_model_details()

    def _configure_preprocessing(self) -> None:
        """Read the preprocessing knobs once (env is not re-read per frame).

        Split out of ``__init__`` so tests can build a manager without a
        TensorRT interpreter (``ModelManager.__new__`` + this + ``input_details``).
        """
        self._pad_value = letterbox_pad_from_env()
        self._resize_interp = resize_interp_from_env()
        self._tiling_mode = tiling_mode_from_env()
        self._tiling_tile = tiling_tile_from_env()
        self._tiling_overlap = tiling_overlap_from_env()
        try:
            decode_scale = int(os.environ.get("PROCESSING_DECODE_SCALE", "1"))
        except ValueError:
            decode_scale = 1
        if self._tiling_mode == "grid" and decode_scale > 1:
            logger.warning(
                "TILING_MODE=grid with PROCESSING_DECODE_SCALE=%d: tiles are cut "
                "from the reduced-scale frame; set PROCESSING_DECODE_SCALE=1 so "
                "tiling sees native pixels", decode_scale)

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
    
    def preprocess_image(self, image_original) -> tuple[np.ndarray, float, int, int]:
        """Letterbox, colour-convert and pack a BGR frame into the model input tensor.

        The frame is resized so its width fills the model input, the height is
        centred between constant-colour bands (Y-only letterbox), BGR becomes
        RGB and the result is laid out as NCHW (float32 in 0..1) for
        channels-first engines or NHWC otherwise.

        Training parity: ultralytics letterboxes with gray (114) padding and
        resizes with ``INTER_LINEAR``, while this path has always used black (0)
        padding and ``INTER_NEAREST``. The mismatch mostly costs recall on small
        objects near the pad bands and adds aliasing on strong downscales, which
        matters more at imgsz 1280 than at 640. Both are configurable via
        ``INFER_LETTERBOX_PAD`` and ``INFER_RESIZE_INTERP`` (read once in
        ``_configure_preprocessing``); the defaults are what the deployed engines
        are validated with.

        Args:
            image_original: Original OpenCV (BGR) image.

        Returns:
            tuple: ``(input_tensor, scale, border_top, actual_input_size)``.
        """
        expected_shape = self.input_details[0]['shape']

        # Channels-first (ONNX/TensorRT) vs channels-last layout.
        is_channels_first = (len(expected_shape) == 4 and expected_shape[1] == 3)

        if is_channels_first:
            actual_input_size = int(expected_shape[2])
        else:
            actual_input_size = self.input_size

        image, scale, border_top = letterbox_to_square(
            image_original, actual_input_size, self._pad_value, self._resize_interp)

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
                input_tensor = (input_tensor.astype(np.float32) - 127.5) / 127.5

        return input_tensor, scale, border_top, actual_input_size

    @property
    def tiling_active(self) -> bool:
        """True when ``TILING_MODE=grid`` sliced inference is enabled."""
        return self._tiling_mode == "grid"

    def preprocess_tiles(self, image_original):
        """Preprocess a frame into one or more model inputs.

        With ``TILING_MODE=off`` this is exactly ``preprocess_image`` wrapped
        in single-element lists. With ``grid`` (default) the frame is sliced
        into overlapping square tiles (geometry from ``conecsa_common.tiling``,
        the same module the training-service crops the dataset with, so the
        deployed layout is byte-for-byte the one trained on) and each crop is
        letterboxed independently.

        Returns ``(tensors, metas)`` — parallel lists of input tensors and
        :class:`TileMeta` entries the detector uses to map corners back into
        frame space.
        """
        frame_h, frame_w = image_original.shape[:2]
        if not self.tiling_active:
            input_tensor, scale, border_top, input_size = self.preprocess_image(image_original)
            return [input_tensor], [TileMeta(scale, border_top, input_size, 0, 0, frame_w, frame_h)]

        # Imported lazily: only a base image built with this feature ships
        # conecsa_common.tiling, and the off path must not depend on it.
        from conecsa_common.tiling import auto_tile, tile_crop, tile_grid

        side = self._tiling_tile or auto_tile(frame_w, frame_h)
        tensors = []
        metas = []
        for tile in tile_grid(frame_w, frame_h, side, self._tiling_overlap):
            crop = tile_crop(image_original, tile)
            input_tensor, scale, border_top, input_size = self.preprocess_image(crop)
            tensors.append(input_tensor)
            metas.append(TileMeta(scale, border_top, input_size,
                                  tile.x0, tile.y0, tile.width, tile.height))
        return tensors, metas

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
