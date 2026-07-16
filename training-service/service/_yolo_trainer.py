"""Standalone ultralytics YOLO trainer (subprocess).

Executed by training_service.TrainingService so torch/ultralytics state dies
with this process (same isolation rule as the inference-service's
_pt_onnx_converter). Unlike the converter, progress streams while it runs:
one JSON line per epoch on stdout, then a final done/error line.

Stdout contract (one JSON object per line, flushed):
    {"epoch": 3, "total": 50, "metrics": {...}}     after each epoch
    {"stopping": true}                              early stop requested (SIGUSR1)
    {"done": true, "best": ".../weights/best.pt",
     "last": ".../weights/last.pt"}                 on success (last line)
    {"error": "..."}                                on failure (last line)

A SIGUSR1 from the parent requests a *graceful* early stop: the next epoch
boundary flips ultralytics' own ``trainer.stop`` switch, so the run finishes
the current epoch, runs final validation, writes best.pt and exits 0 — keeping
the model (unlike SIGTERM, which the parent uses to hard-cancel and discard).

Usage:
    python3 -m service._yolo_trainer --data .../data.yaml \\
        --weights /app/training-service/assets/yolo26s.pt \\
        --epochs 50 --batch 4 --imgsz 640 --workers 0 \\
        --project /data/training/runs --name {job_id}

NOTE on DataLoader workers: this container shares webcam-server's IPC namespace
(``ipc: service:webcam-server``) so it can read the camera SHM ring, which means
it also inherits that namespace's small (~64MB) ``/dev/shm``. PyTorch DataLoader
worker processes pass loaded tensors through ``/dev/shm``, and >0 workers
exhaust it instantly ("unable to allocate shared memory ... Resource temporarily
unavailable"). Default to ``--workers 0`` (single-process loading — trivial for
a 20-image dataset) and force the file_system sharing strategy as a backstop.
"""
import argparse
import json
import logging
import os
import signal
import sys

log = logging.getLogger(__name__)

# Set by the SIGUSR1 handler; checked at each epoch boundary to flip
# ultralytics' graceful-stop switch. Module-level so the signal handler (which
# can't take extra args) and the training callback can share it.
_stop_requested = False


def _emit(payload: dict) -> None:
    """Emit."""
    print(json.dumps(payload), flush=True)


def main() -> None:
    """Main."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stderr,
    )

    parser = argparse.ArgumentParser(description="YOLO trainer (subprocess)")
    parser.add_argument("--data", required=True, help="Path to data.yaml")
    parser.add_argument("--weights", required=True, help="Base .pt weights")
    parser.add_argument("--epochs", type=int, required=True)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--project", required=True, help="ultralytics project dir")
    parser.add_argument("--name", required=True, help="run name (job id)")
    parser.add_argument("--patience", type=int, default=50,
                        help="epochs without improvement before early stop")
    parser.add_argument("--no-amp", action="store_true")
    args = parser.parse_args()

    # Parent sends SIGUSR1 to request a graceful early stop (keep best.pt).
    def _on_sigusr1(_signum, _frame) -> None:
        """On sigusr1."""
        global _stop_requested
        _stop_requested = True

    signal.signal(signal.SIGUSR1, _on_sigusr1)

    # The device may be offline: keep ultralytics away from its auto-download
    # paths (AMP check resolves base weights relative to cwd; fonts/plots are
    # disabled via plots=False).
    os.chdir(os.path.dirname(os.path.abspath(args.weights)))

    try:
        import torch  # heavy import, subprocess-only

        # Backstop for the shared small /dev/shm (see module docstring): the
        # file_system strategy passes shared tensors via temp files instead of
        # /dev/shm file descriptors, so any stray multiprocessing path (e.g.
        # pin_memory) cannot exhaust the segment.
        try:
            torch.multiprocessing.set_sharing_strategy("file_system")
        except Exception:  # noqa: BLE001 - best effort
            pass

        from ultralytics import YOLO  # heavy import, subprocess-only

        model = YOLO(args.weights)

        total = args.epochs

        def on_epoch_end(trainer) -> None:
            """On epoch end."""
            metrics = {}
            try:
                metrics = {k: float(v) for k, v in (trainer.metrics or {}).items()}
            except Exception:  # noqa: BLE001 - metrics are best-effort telemetry
                pass
            _emit({"epoch": int(trainer.epoch) + 1, "total": total, "metrics": metrics})

        model.add_callback("on_train_epoch_end", on_epoch_end)

        # On a graceful-stop request, flip ultralytics' own early-stop switch at
        # the fit-epoch boundary (where it also evaluates `patience`); the run
        # then finalizes validation + best.pt and returns normally.
        def on_fit_epoch_end(trainer) -> None:
            """On fit epoch end."""
            if _stop_requested and not getattr(trainer, "stop", False):
                trainer.stop = True
                _emit({"stopping": True})

        model.add_callback("on_fit_epoch_end", on_fit_epoch_end)

        results = model.train(
            data=args.data,
            epochs=args.epochs,
            patience=args.patience,
            batch=args.batch,
            imgsz=args.imgsz,
            workers=args.workers,
            device=0,
            amp=not args.no_amp,
            cache=False,
            plots=False,
            exist_ok=True,
            project=args.project,
            name=args.name,
            verbose=False,
        )

        best = os.path.join(str(getattr(results, "save_dir", "")), "weights", "best.pt")
        if not os.path.exists(best):
            best = os.path.join(args.project, args.name, "weights", "best.pt")
        if not os.path.exists(best):
            raise RuntimeError(f"Training finished but best.pt not found at {best}")
        # last.pt (final-epoch weights) sits next to best.pt; federated rounds
        # average it instead of best.pt so every device contributes the same
        # number of local epochs.
        last = os.path.join(os.path.dirname(best), "last.pt")
        _emit({"done": True, "best": best,
               "last": last if os.path.exists(last) else best})

    except Exception as exc:  # noqa: BLE001 - contract: last line carries the error
        log.exception("FATAL: %s", exc)
        _emit({"error": str(exc)})
        sys.exit(1)


if __name__ == "__main__":
    main()
