"""Standalone FedAvg checkpoint averager (subprocess).

Executed by the AverageWeights RPC so torch state dies with this process
(same isolation rule as _yolo_trainer). CPU-only: checkpoints are loaded with
``map_location="cpu"``, so averaging never competes with a GPU training job.

Averages ultralytics .pt checkpoints key-by-key over the ``model`` and ``ema``
state dicts (``YOLO(path)`` loads ``ema or model``, so both must be averaged):
floating tensors are averaged in fp32 and cast back to their original dtype;
non-float buffers (e.g. BatchNorm ``num_batches_tracked``) are kept from the
first checkpoint. Mismatched key sets or shapes abort — that means the
checkpoints were not trained from the same architecture/class head. The output
reuses the first checkpoint's container with ``optimizer`` dropped (meaningless
after averaging, and it halves the file size).

Stdout contract (single JSON line, flushed):
    {"done": true, "output": "/data/training/weights/....pt"}   on success
    {"error": "..."}                                            on failure

Usage:
    python3 -m service._weights_averager --inputs a.pt b.pt ... --output out.pt
"""
import argparse
import json
import logging
import sys

log = logging.getLogger(__name__)


def _emit(payload: dict) -> None:
    """Emit."""
    print(json.dumps(payload), flush=True)


def _average_state_dicts(state_dicts: list) -> dict:
    """Average a list of aligned state dicts (fp32 math, original dtypes out)."""
    import torch  # heavy import, subprocess-only

    keys = set(state_dicts[0].keys())
    for i, sd in enumerate(state_dicts[1:], start=2):
        if set(sd.keys()) != keys:
            raise RuntimeError(
                f"Checkpoint {i} has a different parameter set — "
                "all inputs must share one architecture and class head"
            )

    averaged = {}
    for key in state_dicts[0]:
        tensors = [sd[key] for sd in state_dicts]
        first = tensors[0]
        for i, t in enumerate(tensors[1:], start=2):
            if t.shape != first.shape:
                raise RuntimeError(
                    f"Checkpoint {i} has a mismatched shape for '{key}' "
                    f"({tuple(t.shape)} vs {tuple(first.shape)})"
                )
        if first.is_floating_point():
            acc = torch.zeros_like(first, dtype=torch.float32)
            for t in tensors:
                acc += t.float()
            averaged[key] = (acc / len(tensors)).to(first.dtype)
        else:
            averaged[key] = first
    return averaged


def _merge_checkpoints(ckpts: list) -> dict:
    """FedAvg-merge loaded checkpoints into the first one's container."""
    merged = ckpts[0]
    if merged.get("model") is None:
        raise RuntimeError("First checkpoint carries no 'model' module")

    # Average 'ema' only when every input has one; otherwise drop it so
    # YOLO(path) falls back to the averaged 'model'.
    for key in ("model", "ema"):
        modules = [c.get(key) for c in ckpts]
        if any(m is None for m in modules):
            if key == "ema":
                merged["ema"] = None
                continue
            raise RuntimeError("A checkpoint carries no 'model' module")
        averaged = _average_state_dicts([m.state_dict() for m in modules])
        modules[0].load_state_dict(averaged)
        merged[key] = modules[0]

    merged["optimizer"] = None
    return merged


def main() -> None:
    """Main."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="FedAvg checkpoint averager (subprocess)")
    parser.add_argument("--inputs", nargs="+", required=True,
                        help="Two or more .pt checkpoints to average")
    parser.add_argument("--output", required=True, help="Averaged .pt destination")
    args = parser.parse_args()

    try:
        if len(args.inputs) < 2:
            raise RuntimeError("Averaging needs at least two checkpoints")

        import torch  # heavy import, subprocess-only

        ckpts = [torch.load(p, map_location="cpu", weights_only=False)
                 for p in args.inputs]
        merged = _merge_checkpoints(ckpts)
        torch.save(merged, args.output)
        _emit({"done": True, "output": args.output})

    except Exception as exc:  # noqa: BLE001 - contract: last line carries the error
        log.exception("FATAL: %s", exc)
        _emit({"error": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
