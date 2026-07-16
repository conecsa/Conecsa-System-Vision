"""Training job orchestration.

One job at a time. The ultralytics run executes in a child process
(_yolo_trainer) that streams one JSON line per epoch; a reader thread folds
those into the job state and publishes ``training_progress`` events. On
success the resulting best.pt is uploaded through the api-gateway's existing
model-upload route, which renames it to the user-chosen model name and starts
the pt→onnx→engine conversion on the inference-service (classes sidecar and
SSE included) — the same path a manual upload takes.

Federated rounds (hub-orchestrated FedAvg) reuse the same job machinery but
start from a stashed checkpoint (``initial_weights_id``) and, instead of
uploading, stash the resulting last.pt back into the weights store
(``result_weights_id``) for the hub to collect and average.
"""
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional

import requests

from .config import Config
from .dataset_registry import DatasetRegistry
from .dataset_service import DatasetError, DatasetService, validate_model_name

logger = logging.getLogger(__name__)

_TERMINAL = {"done", "failed", "canceled"}


@dataclass
class TrainingJob:
    """State of a single training run (status, progress, epoch, metrics, result)."""

    job_id: str = ""
    status: str = "idle"      # idle/preparing/training/uploading/done/failed/canceled
    progress: int = 0         # 0-100
    epoch: int = 0
    total_epochs: int = 0
    message: str = ""
    error: str = ""
    model_name: str = ""
    conversion_job_id: str = ""
    metrics: Dict = field(default_factory=dict)
    started_at: float = 0.0
    dataset_id: str = ""
    patience: int = 0
    # Federated round (hub-orchestrated FedAvg): the result stays on-device as
    # a stashed checkpoint instead of going through the model-upload route.
    federated: bool = False
    result_weights_id: str = ""


class TrainingService:
    """Orchestrates one ultralytics training job at a time.

    Runs the trainer in a child process (``_yolo_trainer``) that streams
    per-epoch JSON; a reader thread folds those into the :class:`TrainingJob`
    state and publishes ``training_progress`` events. On success it hands
    ``best.pt`` to the gateway's model-upload route (pt→onnx→engine).
    """

    def __init__(self, config: Config, registry: DatasetRegistry,
                 event_service=None, sam_service=None, weights_store=None):
        self._config = config
        self._registry = registry
        self._events = event_service
        self._sam = sam_service
        # Stash for federated rounds (initial weights in, last.pt out).
        self._weights = weights_store
        self._lock = threading.Lock()
        self._job = TrainingJob()
        # Dataset of the running job; frozen for the job's duration.
        self._job_dataset: Optional[DatasetService] = None
        self._process: Optional[subprocess.Popen] = None
        self._cancel_requested = False
        # Graceful early-stop (keep best.pt), distinct from a hard cancel.
        self._early_stop_requested = False
        # Monotonic timestamp of the trainer's last stdout/stderr line,
        # written by the reader threads and watched by the stall watchdog.
        self._last_output = 0.0

    # ── public API ────────────────────────────────────────────────────────────

    def get_job(self) -> TrainingJob:
        """Get job."""
        with self._lock:
            return TrainingJob(**vars(self._job))

    def is_active(self) -> bool:
        """Is active."""
        with self._lock:
            return self._job.status not in ("idle", *_TERMINAL)

    def start(self, dataset_id: str, model_name: str,
              epochs: int = 0, batch: int = 0, patience: int = 0,
              initial_weights_id: str = "", federated: bool = False) -> TrainingJob:
        """Start."""
        if federated:
            # No model upload happens, so the name is only a display label.
            model_name = (model_name or "").strip() or "federated"
        else:
            model_name = validate_model_name(model_name)
        epochs = epochs or self._config.DEFAULT_EPOCHS
        batch = batch or self._config.TRAIN_BATCH
        patience = patience or self._config.DEFAULT_PATIENCE
        if epochs < 1 or epochs > 1000:
            raise DatasetError("Epochs must be between 1 and 1000")
        dataset = self._registry.get(dataset_id)

        # Resolve the starting checkpoint up front so an unknown id fails the
        # RPC instead of the job.
        weights_path = self._config.BASE_WEIGHTS
        if initial_weights_id:
            if self._weights is None:
                raise DatasetError("Weights store is not available")
            weights_path = self._weights.path(initial_weights_id)

        with self._lock:
            if self._job.status not in ("idle", *_TERMINAL):
                raise DatasetError("A training job is already running")
            dataset.validate_for_training()
            job_id = str(uuid.uuid4())
            self._job = TrainingJob(
                job_id=job_id, status="preparing", progress=2,
                message="Preparing dataset split…",
                model_name=model_name, total_epochs=epochs,
                started_at=time.time(), dataset_id=dataset_id,
                patience=patience, federated=federated,
            )
            self._cancel_requested = False
            self._early_stop_requested = False
            self._job_dataset = dataset
            dataset.frozen = True

        # SAM and training never share the GPU (8GB budget).
        if self._sam is not None:
            self._sam.unload()

        threading.Thread(
            target=self._run, args=(job_id, epochs, batch, patience, weights_path),
            daemon=True, name=f"training-{job_id[:8]}",
        ).start()
        self._publish()
        return self.get_job()

    def cancel(self) -> bool:
        """Cancel."""
        with self._lock:
            if self._job.status not in ("preparing", "training"):
                return False
            self._cancel_requested = True
            proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError) as exc:
                logger.warning("Cancel signal failed: %s", exc)
        return True

    def finish_early(self) -> bool:
        """Gracefully stop the running job, keeping the best model so far.

        Unlike cancel (SIGTERM/kill → discarded), this nudges the trainer with
        SIGUSR1 so ultralytics finalizes the current epoch + validation, writes
        best.pt and exits 0 — the normal done/upload/conversion path then runs.
        """
        with self._lock:
            if self._job.status != "training":
                return False
            self._early_stop_requested = True
            proc = self._process
        if proc is None or proc.poll() is not None:
            return False
        try:
            # pid only (not the group) — a graceful signal, never a kill.
            os.kill(proc.pid, signal.SIGUSR1)
        except (ProcessLookupError, PermissionError) as exc:
            logger.warning("Finish-early signal failed: %s", exc)
            return False
        self._set(message="Finishing early — finalizing model…")
        return True

    # ── internals ─────────────────────────────────────────────────────────────

    def _set(self, **fields) -> None:
        """Set."""
        with self._lock:
            for k, v in fields.items():
                setattr(self._job, k, v)
        self._publish()

    def _publish(self) -> None:
        """Publish."""
        if self._events is None:
            return
        job = self.get_job()
        try:
            self._events.publish(
                "training_progress", keys=["training"],
                data={
                    "job_id": job.job_id, "status": job.status,
                    "progress": job.progress, "epoch": job.epoch,
                    "total_epochs": job.total_epochs, "message": job.message,
                    "error": job.error, "model_name": job.model_name,
                    "conversion_job_id": job.conversion_job_id,
                    "dataset_id": job.dataset_id,
                    "federated": job.federated,
                    "result_weights_id": job.result_weights_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not publish training event: %s", exc)

    def _run(self, job_id: str, epochs: int, batch: int, patience: int,
             weights_path: str) -> None:
        """Run."""
        dataset = self._job_dataset
        assert dataset is not None
        try:
            data_yaml = dataset.build_split(job_id)
            self._set(status="training", progress=5,
                      message=f"Training {epochs} epochs…")

            cmd = [
                sys.executable, "-m", "service._yolo_trainer",
                "--data", data_yaml,
                "--weights", weights_path,
                "--epochs", str(epochs),
                "--patience", str(patience),
                "--batch", str(batch),
                "--imgsz", str(self._config.IMG_SIZE),
                "--workers", str(self._config.TRAIN_WORKERS),
                "--project", self._config.runs_dir,
                "--name", job_id,
            ]
            if not self._config.TRAIN_AMP:
                cmd.append("--no-amp")

            env = os.environ.copy()
            env["PYTHONPATH"] = "/app/training-service"

            logger.info("Starting trainer subprocess for job %s", job_id)
            with self._lock:
                self._process = subprocess.Popen(
                    cmd, env=env, start_new_session=True,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                proc = self._process

            stderr_thread = threading.Thread(
                target=self._drain_stderr, args=(proc,), daemon=True,
                name=f"training-stderr-{job_id[:8]}",
            )
            stderr_thread.start()

            # Watchdog: stdout consumption below blocks until the trainer
            # exits, so hang detection has to come from the side. It fires on
            # output silence (stalled/hung trainer), not on total duration —
            # long runs are legitimate. `timed_out` carries the kill reason.
            self._last_output = time.monotonic()
            timed_out: list = []
            watchdog = threading.Thread(
                target=self._watch_trainer, args=(proc, timed_out),
                daemon=True, name=f"training-watchdog-{job_id[:8]}",
            )
            watchdog.start()
            best_path, last_path = self._consume_stdout(proc, epochs)
            proc.wait()

            if timed_out:
                raise RuntimeError(timed_out[0])
            if self._cancel_requested:
                self._set(status="canceled", message="Training canceled", progress=0)
                return
            if proc.returncode != 0 or best_path is None:
                raise RuntimeError(
                    self.get_job().error or
                    f"Trainer exited with code {proc.returncode}"
                )

            if self.get_job().federated:
                # Federated round: the hub collects last.pt for averaging, so
                # the result stays on-device instead of going through the
                # model-upload/conversion route.
                assert self._weights is not None
                weights_id = self._weights.stash_file(last_path or best_path)
                self._set(status="done", progress=100,
                          result_weights_id=weights_id,
                          message="Training complete; weights retained for aggregation")
                logger.info("Job %s done; weights stashed as %s", job_id, weights_id)
            else:
                conversion_job_id = self._upload_best(best_path)
                self._set(status="done", progress=100,
                          conversion_job_id=conversion_job_id,
                          message="Training complete; model uploaded for conversion")
                logger.info("Job %s done; conversion job %s", job_id, conversion_job_id)

        except Exception as exc:  # noqa: BLE001 - job state carries the failure
            logger.exception("Training job %s failed: %s", job_id, exc)
            if self._cancel_requested:
                self._set(status="canceled", message="Training canceled", progress=0)
            else:
                self._set(status="failed", error=str(exc),
                          message="Training failed", progress=0)
        finally:
            with self._lock:
                self._process = None
                self._job_dataset = None
            dataset.frozen = False

    def _consume_stdout(self, proc: subprocess.Popen,
                        epochs: int) -> "tuple[Optional[str], Optional[str]]":
        """Fold the trainer's JSON lines into the job; return (best, last) paths."""
        best_path: Optional[str] = None
        last_path: Optional[str] = None
        assert proc.stdout is not None
        for line in proc.stdout:
            self._last_output = time.monotonic()
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except ValueError:
                logger.debug("[trainer] %s", line)
                continue
            if payload.get("error"):
                self._set(error=str(payload["error"]))
            elif payload.get("stopping"):
                self._set(message="Finishing early — finalizing model…")
            elif payload.get("done"):
                best_path = str(payload.get("best", ""))
                last_path = str(payload.get("last", "")) or None
            elif payload.get("epoch"):
                epoch = int(payload["epoch"])
                progress = 5 + int(epoch / max(epochs, 1) * 90)
                self._set(epoch=epoch, progress=min(progress, 95),
                          metrics=payload.get("metrics") or {},
                          message=f"Epoch {epoch}/{epochs}")
        return best_path, last_path

    def _watch_trainer(self, proc: subprocess.Popen, timed_out: list) -> None:
        """Kill the trainer on output silence (hang) or the optional hard cap."""
        start = time.monotonic()
        while proc.poll() is None:
            time.sleep(15)
            now = time.monotonic()
            cap = self._config.TRAIN_TIMEOUT_SEC
            stall = self._config.TRAIN_STALL_TIMEOUT_SEC
            if cap and now - start > cap:
                reason = f"Training exceeded the {cap}s limit (TRAIN_TIMEOUT_SEC)"
            elif now - self._last_output > stall:
                reason = (
                    f"Training stalled: no trainer output for {stall}s "
                    f"(TRAIN_STALL_TIMEOUT_SEC)"
                )
            else:
                continue
            logger.error("%s; killing trainer", reason)
            timed_out.append(reason)
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            return

    def _drain_stderr(self, proc: subprocess.Popen) -> None:
        # Ultralytics writes its progress bars and tracebacks to stderr; keep
        # them in our logs and keep the pipe from filling up and blocking it.
        """Drain stderr."""
        assert proc.stderr is not None
        for line in proc.stderr:
            self._last_output = time.monotonic()
            line = line.rstrip()
            if line:
                logger.info("[trainer] %s", line)

    def _upload_best(self, best_path: str) -> str:
        """Upload best.pt as {model_name}.pt through the gateway.

        The gateway relays to ModelControl.UploadModel on the inference-service,
        which saves it under /data/models and starts the pt→onnx→engine
        conversion job (returned here so the frontend can track it).
        """
        job = self.get_job()
        self._set(status="uploading", progress=97,
                  message="Uploading model for conversion…")
        url = f"{self._config.GATEWAY_ADDR}/api/v1/model"
        with open(best_path, "rb") as f:
            resp = requests.post(
                url,
                files={"file": (f"{job.model_name}.pt", f)},
                data={"imgsz": str(self._config.IMG_SIZE)},
                timeout=120,
            )
        if resp.status_code not in (200, 202):
            raise RuntimeError(
                f"Model upload failed (HTTP {resp.status_code}): {resp.text[:200]}"
            )
        try:
            return str(resp.json().get("job_id") or "")
        except ValueError:
            return ""
