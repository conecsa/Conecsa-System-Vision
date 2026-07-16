"""
Standalone TensorRT engine builder script.

Intended to be executed by the PyTorch venv Python interpreter via subprocess,
since tensorrt is only available inside that venv.

Usage:
    <pytorch_venv>/bin/python -m api.runtime_management._trt_engine_builder \
        --onnx <path_to.onnx> \
        --engine <path_to.engine> \
        --workspace-mb 256
"""
import argparse
import logging
import os
import sys

log = logging.getLogger(__name__)


def ensure_cudla_compat() -> None:
    """Ensure libcudla soname is available, preferring the real CUDA libcudla library."""
    lib_dir = "/usr/lib/aarch64-linux-gnu"
    expected = os.path.join(lib_dir, "libcudla.so.1")
    cuda_cudla = "/usr/local/cuda-12.6/targets/aarch64-linux/lib/libcudla.so.1.0.0"

    if os.path.exists(expected):
        return

    if not os.path.exists(cuda_cudla):
        return

    try:
        os.symlink(cuda_cudla, expected)
    except FileExistsError:
        pass
    except OSError:
        # Non-fatal: if symlink cannot be created, TensorRT import may still fail and report clearly.
        pass

    legacy_link = os.path.join(lib_dir, "libcudla.so")
    if not os.path.exists(legacy_link):
        try:
            os.symlink(expected, legacy_link)
        except (FileExistsError, OSError):
            pass


def _get_workspace_sizes(preferred_mb: int = 256) -> list:
    """
    Get list of workspace sizes to try for engine building.

    Returns:
        List of workspace sizes in MB
    """
    try:
        preferred_mb = int(os.environ.get('TENSORRT_WORKSPACE_MB', str(preferred_mb)))
    except ValueError:
        pass

    candidates: list = []
    for mb in (preferred_mb, 256, 192, 128):
        if mb > 0 and mb not in candidates:
            candidates.append(mb)
    return candidates


def build_engine(onnx_path: str, engine_path: str, workspace_mb: int = 256) -> None:
    """Build a TensorRT ``.engine`` from an ONNX model within *workspace_mb*."""
    ensure_cudla_compat()

    import tensorrt as trt  # type: ignore[import-untyped]

    trt_logger = trt.Logger(trt.Logger.WARNING)  # type: ignore[attr-defined]

    builder = trt.Builder(trt_logger)  # type: ignore[attr-defined]
    network = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)  # type: ignore[attr-defined]
    )
    parser = trt.OnnxParser(network, trt_logger)  # type: ignore[attr-defined]

    log.info("[trt_builder] Parsing ONNX: %s", onnx_path)
    with open(onnx_path, "rb") as f:
        if not parser.parse(f.read()):
            for i in range(parser.num_errors):
                log.error("  ONNX parse error: %s", parser.get_error(i))
            raise RuntimeError("Failed to parse ONNX model")

    workspace_candidates = _get_workspace_sizes(workspace_mb)

    serialized_engine = None
    for mb in workspace_candidates:
        try:
            config = builder.create_builder_config()
            config.set_memory_pool_limit(
                trt.MemoryPoolType.WORKSPACE, mb * (1 << 20)  # type: ignore[attr-defined]
            )
            if builder.platform_has_fast_fp16:
                config.set_flag(trt.BuilderFlag.FP16)  # type: ignore[attr-defined]

            log.info("[trt_builder] Building engine (workspace=%s MB)…", mb)
            serialized_engine = builder.build_serialized_network(network, config)
            if serialized_engine is not None:
                break
        except (RuntimeError, OSError) as exc:
            log.warning("[trt_builder] Build attempt failed (%s MB): %s", mb, exc)

    if serialized_engine is None:
        raise RuntimeError("TensorRT engine build failed for all workspace sizes")

    with open(engine_path, "wb") as f:
        f.write(serialized_engine)

    log.info("[trt_builder] Engine saved: %s", engine_path)


def main() -> None:
    """CLI entry point for the TensorRT engine-builder subprocess."""
    parser = argparse.ArgumentParser(description="TensorRT engine builder (venv subprocess)")
    parser.add_argument("--onnx", required=True, help="Path to ONNX model")
    parser.add_argument("--engine", required=True, help="Output .engine path")
    parser.add_argument("--workspace-mb", type=int, default=256, help="TRT workspace in MB")
    args = parser.parse_args()

    try:
        build_engine(args.onnx, args.engine, args.workspace_mb)
    except (RuntimeError, OSError) as exc:
        log.critical("[trt_builder] FATAL: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
