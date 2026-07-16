"""Standalone SAM3 segmentation worker (subprocess).

Owns the SAM3 model on the GPU so the long-lived gRPC parent never imports
torch. Terminating this process is the unload path — the kernel reclaims the
~2-3GB the model pins, which is the only reliable way to free it on the 8GB
Orin Nano. Mirrors the worker_server.py Listener pattern of the
inference-service TensorRT worker.

Commands (multiprocessing.connection, authkey b"conecsa"):
    {"cmd": "load"}                          → {"status": "ok"} (model on GPU)
    {"cmd": "segment", "image_path": ...,
     "text_prompt": "...", "points": [...]}  → {"status": "ok", "boxes": [...], "scores": [...]}
    {"cmd": "close"}                         → {"status": "ok"} then exits

Boxes are returned normalized YOLO (cx, cy, w, h in 0..1) so the parent can
relay them without knowing the image size.
"""
import argparse
import contextlib
import logging
import os
import sys
import threading
import time
import traceback
from multiprocessing.connection import Listener
from typing import Any, Dict, List, Optional, Tuple

AUTH_KEY = b"conecsa"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

#: torch.nn.init fillers to no-op while the model is built: every parameter
#: they touch is overwritten by the checkpoint right after, so the random
#: fill is pure wasted CPU (~850M params on the Orin's ARM cores).
_INIT_FNS = (
    "uniform_", "normal_", "trunc_normal_", "constant_", "ones_", "zeros_",
    "eye_", "dirac_", "xavier_uniform_", "xavier_normal_",
    "kaiming_uniform_", "kaiming_normal_", "orthogonal_", "sparse_",
)


@contextlib.contextmanager
def _skip_param_init(torch):
    """No-op the torch.nn.init module fillers for the duration of the block.

    Only module-attribute lookups (``init.kaiming_uniform_(...)`` in
    ``reset_parameters``) are intercepted — early-bound ``from torch.nn.init
    import …`` references and Tensor methods keep running, so arithmetic
    buffers (rope tables, positional encodings) are never affected.
    """
    saved = {n: getattr(torch.nn.init, n)
             for n in _INIT_FNS if hasattr(torch.nn.init, n)}

    def _noop(tensor, *args, **kwargs):
        return tensor

    for n in saved:
        setattr(torch.nn.init, n, _noop)
    try:
        yield
    finally:
        for n, fn in saved.items():
            setattr(torch.nn.init, n, fn)


def _warm_page_cache(path: str) -> None:
    """Sequentially read the checkpoint so its pages are hot before torch.load
    mmaps it: one full-bandwidth streaming read instead of fault-driven access
    during load_state_dict. Purely advisory; failures are harmless."""
    t0 = time.monotonic()
    try:
        with open(path, "rb", buffering=0) as f:
            chunk = bytearray(32 * 1024 * 1024)
            total = 0
            while True:
                n = f.readinto(chunk)
                if not n:
                    break
                total += n
        logger.info("Checkpoint cache warm: %.2f GB in %.1fs",
                    total / 1e9, time.monotonic() - t0)
    except OSError as exc:
        logger.warning("Checkpoint cache warm failed (harmless): %s", exc)


def _start_cache_warmer(checkpoint: str) -> None:
    """Warm the checkpoint page cache in the background (SAM3_WARM_CACHE=0
    disables). Started at process birth so the read overlaps the torch import
    and the CPU-side model build."""
    if os.environ.get("SAM3_WARM_CACHE", "1") != "1":
        return
    threading.Thread(target=_warm_page_cache, args=(checkpoint,),
                     name="ckpt-warm", daemon=True).start()


class _Sam3Session:
    """Thin adapter around the SAM3 image API (text + point prompts)."""

    def __init__(self, checkpoint: str):
        t0 = time.monotonic()
        import torch  # heavy imports live only in this subprocess
        # sam3 is vendored into /data/training/sam3 on the device and is absent from
        # the host dev venv, so the type checker cannot resolve it here.
        from sam3.model_builder import build_sam3_image_model  # pyright: ignore[reportMissingImports]
        from sam3.model.sam3_image_processor import Sam3Processor  # pyright: ignore[reportMissingImports]

        self._torch = torch
        t_import = time.monotonic()
        logger.info("SAM3 imports: %.1fs", t_import - t0)
        logger.info("Loading SAM3 model from %s", checkpoint)
        # The stock loader reads the whole ~3.4GB fp32 state dict into
        # anonymous RAM on top of the freshly built model — a ~7GB transient
        # peak that OOM-kills this worker on the 8GB Orin Nano (no swap).
        # Force torch.load to mmap the checkpoint instead: tensor storages
        # stay file-backed (page cache, reclaimable under pressure) and the
        # peak drops to roughly the model itself. sam3's _load_checkpoint
        # passes an open file object, which mmap does not accept — substitute
        # the path we already know.
        orig_load = torch.load
        def _mmap_load(_file_obj, *args, **kwargs):
            """Mmap load."""
            kwargs["map_location"] = "cpu"
            kwargs["weights_only"] = True
            kwargs["mmap"] = True
            return orig_load(checkpoint, **kwargs)
        # sam3 loads with strict=False; with the random init skipped a key
        # that the checkpoint does not cover would keep an uninitialized
        # (garbage) tensor instead of merely a wasteful random one. Wrap
        # load_state_dict to surface the gaps loudly and drive the fallback.
        orig_lsd = torch.nn.Module.load_state_dict
        missing: List[str] = []
        def _logging_lsd(self, state_dict, strict=True, assign=False):
            """Load state dict, recording strict=False gaps."""
            try:
                result = orig_lsd(self, state_dict, strict=strict, assign=assign)
            except TypeError as e:
                # Older torch versions don't support the 'assign' kwarg.
                if "assign" not in str(e):
                    raise
                result = orig_lsd(self, state_dict, strict=strict)
            if result.missing_keys:
                missing.extend(result.missing_keys)
                logger.error(
                    "SAM3 load_state_dict: %d MISSING keys (strict=False), "
                    "e.g. %s", len(result.missing_keys),
                    result.missing_keys[:20])
            if result.unexpected_keys:
                logger.warning("SAM3 load_state_dict: %d unexpected keys",
                               len(result.unexpected_keys))
            return result

        skip_init = os.environ.get("SAM3_SKIP_INIT", "1") == "1"
        torch.load = _mmap_load
        torch.nn.Module.load_state_dict = _logging_lsd
        try:
            if skip_init:
                with _skip_param_init(torch):
                    model = build_sam3_image_model(
                        checkpoint_path=checkpoint, load_from_HF=False
                    )
                if missing:
                    # A missing key kept its skipped (garbage) init. Rebuild
                    # with full init — slower, but provably identical to the
                    # pre-optimization behavior.
                    logger.error(
                        "Missing keys with init skipped — rebuilding with "
                        "full init (set SAM3_SKIP_INIT=0 to silence)")
                    import gc
                    del model
                    gc.collect()
                    torch.cuda.empty_cache()
                    model = build_sam3_image_model(
                        checkpoint_path=checkpoint, load_from_HF=False
                    )
            else:
                model = build_sam3_image_model(
                    checkpoint_path=checkpoint, load_from_HF=False
                )
        finally:
            torch.load = orig_load
            torch.nn.Module.load_state_dict = orig_lsd
        t_build = time.monotonic()
        logger.info("SAM3 build+load: %.1fs", t_build - t_import)
        # Weights stay fp32 — sam3 pins parts of the network (decoder FFN
        # etc.) to fp32 via autocast(enabled=False), so converting weights to
        # bf16 breaks those islands with dtype mismatches. The intended
        # inference mode is fp32 weights + the bf16 autocast in segment(),
        # which keeps the big activation maps at half size. SAM3_DTYPE=bf16
        # is left as an experimental knob.
        if os.environ.get("SAM3_DTYPE", "fp32").lower() == "bf16":
            model = model.to(torch.bfloat16)
        # Return the freed fp32 blocks to the system: torch's caching
        # allocator keeps them reserved otherwise, and cuBLAS/cuDNN allocate
        # OUTSIDE that allocator — their handle creation fails at the first
        # matmul even though "free" memory exists inside torch's cache.
        import gc
        gc.collect()
        torch.cuda.empty_cache()
        self._processor = Sam3Processor(model)
        t_done = time.monotonic()
        logger.info(
            "SAM3 model loaded: total %.1fs (imports %.1fs, build+load %.1fs, "
            "finalize %.1fs)", t_done - t0, t_import - t0, t_build - t_import,
            t_done - t_build)

    def segment(
        self,
        image_path: str,
        text_prompt: str,
        points: List[Dict[str, Any]],
        threshold: Optional[float] = None,
    ) -> Tuple[List[Dict[str, float]], List[float]]:
        """Segment."""
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        width, height = image.size

        # Confidence threshold filters the grounding detections
        # (keep = prob > confidence_threshold). Higher → fewer, surer boxes.
        if threshold is not None and threshold > 0.0:
            self._processor.confidence_threshold = float(threshold)

        with self._torch.inference_mode(), self._torch.autocast(
            "cuda", dtype=self._torch.bfloat16
        ):
            state = self._processor.set_image(image)
            if text_prompt:
                output = self._processor.set_text_prompt(
                    state=state, prompt=text_prompt
                )
            elif points:
                output = self._point_prompt(state, points, width, height)
            else:
                raise ValueError("Provide a text prompt or at least one point")

        boxes = _to_list(output.get("boxes"))
        scores = [float(s) for s in _to_list(output.get("scores"))]
        masks = output.get("masks")

        if not boxes and masks is not None:
            boxes = [_mask_to_xyxy(m) for m in _to_list(masks)]
            boxes = [b for b in boxes if b is not None]
            scores = scores or [1.0] * len(boxes)

        norm = [_xyxy_to_yolo(b, width, height) for b in boxes]
        return norm, scores[: len(norm)]

    def _point_prompt(self, state, points, width, height):
        """Click prompts. The SAM3 interactive API name varies between
        releases; try the known spellings and fail with a clear message."""
        coords = [[p["x"] * width, p["y"] * height] for p in points]
        labels = [1 if p.get("positive", True) else 0 for p in points]
        for name in ("set_point_prompt", "add_points", "set_points"):
            fn = getattr(self._processor, name, None)
            if fn is None:
                continue
            try:
                return fn(state=state, points=coords, labels=labels)
            except TypeError:
                return fn(state, coords, labels)
        raise RuntimeError(
            "This SAM3 build has no point-prompt API; use a text prompt instead"
        )


def _to_list(value) -> List:
    """To list."""
    if value is None:
        return []
    tolist = getattr(value, "tolist", None)
    # ``value`` is a duck-typed tensor/ndarray, so its tolist() is untyped.
    raw: Any = tolist() if callable(tolist) else value
    return list(raw)


def _mask_to_xyxy(mask) -> Optional[List[float]]:
    """Mask to xyxy."""
    import numpy as np

    arr = np.asarray(mask).squeeze() > 0.5
    ys, xs = np.where(arr)
    if xs.size == 0:
        return None
    return [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())]


def _xyxy_to_yolo(box, width: int, height: int) -> Dict[str, float]:
    """Xyxy to yolo."""
    x1, y1, x2, y2 = [float(v) for v in box[:4]]
    return {
        "cx": min(max((x1 + x2) / 2.0 / width, 0.0), 1.0),
        "cy": min(max((y1 + y2) / 2.0 / height, 0.0), 1.0),
        "w": min(max((x2 - x1) / width, 0.0), 1.0),
        "h": min(max((y2 - y1) / height, 0.0), 1.0),
    }


def run_server(host: str, port: int, checkpoint: str) -> None:
    """Run server."""
    listener = Listener((host, port), authkey=AUTH_KEY)
    logger.info("SAM worker listening on %s:%d", host, port)
    session: Optional[_Sam3Session] = None

    while True:
        conn = listener.accept()
        try:
            while True:
                msg = conn.recv()
                cmd = msg.get("cmd")
                try:
                    if cmd == "load":
                        if session is None:
                            session = _Sam3Session(checkpoint)
                        conn.send({"status": "ok"})
                    elif cmd == "segment":
                        if session is None:
                            conn.send({"status": "error", "error": "model not loaded"})
                            continue
                        boxes, scores = session.segment(
                            msg.get("image_path", ""),
                            msg.get("text_prompt", ""),
                            msg.get("points", []) or [],
                            msg.get("threshold"),
                        )
                        conn.send({"status": "ok", "boxes": boxes, "scores": scores})
                    elif cmd == "close":
                        conn.send({"status": "ok"})
                        conn.close()
                        listener.close()
                        return
                    else:
                        conn.send({"status": "error", "error": f"unknown command {cmd}"})
                except Exception as exc:  # noqa: BLE001 - report, keep serving
                    logger.error("Command '%s' failed: %s", cmd, exc)
                    logger.error(traceback.format_exc())
                    conn.send({"status": "error", "error": str(exc)})
        except EOFError:
            logger.info("Client disconnected")
            conn.close()


def main() -> None:
    """Main."""
    parser = argparse.ArgumentParser(description="SAM3 worker (subprocess)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--checkpoint", required=True)
    args = parser.parse_args()
    _start_cache_warmer(args.checkpoint)
    try:
        run_server(args.host, args.port, args.checkpoint)
    except Exception as exc:  # noqa: BLE001
        logger.error("Fatal: %s", exc)
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
