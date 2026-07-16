"""
Standalone .pt -> .onnx converter (ultralytics / torch).

Executed by conversion_service.ConversionService as a short-lived subprocess
so that the PyTorch caching allocator and ultralytics global state never
land in the long-lived waitress process heap. When the subprocess exits the
kernel reclaims all of it, which is the only reliable cure for the leaks
observed on the Yocto host (no zram, no swap, glibc fragmentation).

Mirrors the pattern of api.runtime_management._trt_engine_builder.

Usage:
    python3 -m api.runtime_management._pt_onnx_converter \\
        --pt /data/models/foo.pt \\
        --onnx /data/models/foo.onnx \\
        --imgsz 640

Stdout (last line, JSON): {"class_names": ["person", "bicycle", ...]}
"""
import argparse
import json
import logging
import os
import shutil
import sys
from typing import List

log = logging.getLogger(__name__)


def convert_pt_to_onnx(pt_path: str, onnx_path: str, imgsz: int = 640) -> List[str]:
    """Export a YOLO .pt to ONNX. Falls back to raw torch.onnx.export."""
    log.info("Converting %s -> %s (imgsz=%d)", pt_path, onnx_path, imgsz)

    try:
        # noinspection PyPackageRequirements
        from ultralytics import YOLO  # type: ignore
        model = YOLO(pt_path)
        model.export(format="onnx", imgsz=imgsz, dynamic=False, simplify=True)

        class_names: List[str] = []
        if hasattr(model, "names") and isinstance(model.names, dict):
            class_names = [model.names[i] for i in sorted(model.names.keys())]
            log.info("Extracted %d class names: %s", len(class_names), class_names)

        auto_onnx = os.path.splitext(pt_path)[0] + ".onnx"
        if auto_onnx != onnx_path:
            shutil.move(auto_onnx, onnx_path)

        log.info("ONNX conversion complete: %s", onnx_path)
        return class_names

    except ImportError:
        log.warning("ultralytics not installed, trying torch.onnx.export fallback")

    # noinspection PyPackageRequirements
    import torch  # type: ignore

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.load(pt_path, map_location=device)
    model.eval()

    dummy = torch.zeros(1, 3, imgsz, imgsz, device=device)
    torch.onnx.export(
        model,
        (dummy,),
        onnx_path,
        opset_version=12,
        input_names=["images"],
        output_names=["output0"],
        dynamic_axes=None,
    )
    log.info("ONNX fallback export complete: %s", onnx_path)
    return []


def main() -> None:
    """CLI entry point for the `.pt`→`.onnx` conversion subprocess."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description=".pt -> .onnx converter (subprocess)")
    parser.add_argument("--pt", required=True, help="Path to .pt model")
    parser.add_argument("--onnx", required=True, help="Output .onnx path")
    parser.add_argument("--imgsz", type=int, default=640, help="Input image size")
    args = parser.parse_args()

    try:
        class_names = convert_pt_to_onnx(args.pt, args.onnx, args.imgsz)
    except Exception as exc:
        log.exception("FATAL: %s", exc)
        print(json.dumps({"error": str(exc)}), flush=True)
        sys.exit(1)

    # Last stdout line is the machine-readable result for the parent.
    print(json.dumps({"class_names": class_names}), flush=True)


if __name__ == "__main__":
    main()
