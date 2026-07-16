"""
Conversion service - Manages async model conversion jobs.

Supports:
  .pt  → .onnx   (via subprocess → api.runtime_management._pt_onnx_converter)
  .onnx → .engine (via TensorRT worker IPC → _trt_engine_builder.build_engine)

The .pt -> .onnx step runs in a short-lived subprocess (NOT in this waitress
process) so that PyTorch caching allocator and ultralytics global state are
fully reclaimed by the OS when the converter exits. This remains important on
the Yocto host: zram/compressed swap may be configured, but fragmentation and
allocator state are still best handled by subprocess isolation and process exit.
"""
import json
import os
import subprocess
import sys
import time
import uuid
import logging
import threading
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Timeout for the .pt -> .onnx subprocess. YOLO export on Orin Nano is
# usually under 2 min; 10 min is a wide safety margin.
_PT_ONNX_TIMEOUT_SEC = int(os.environ.get("PT_ONNX_TIMEOUT_SEC", "600"))


class ConversionStatus(str, Enum):
    """Lifecycle states of a `.pt`→`.onnx`→`.engine` conversion job."""

    PENDING = "pending"
    CONVERTING_TO_ONNX = "converting_to_onnx"
    CONVERTING_TO_ENGINE = "converting_to_engine"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ConversionJob:
    """State of one asynchronous model-conversion job (paths, status, progress)."""

    job_id: str
    original_filename: str
    pt_path: str
    onnx_path: str
    engine_path: str
    status: ConversionStatus = ConversionStatus.PENDING
    progress: int = 0          # 0–100
    message: str = ""
    error: Optional[str] = None
    engine_filename: Optional[str] = None  # basename after conversion
    started_at: float = field(default_factory=time.time)  # UNIX timestamp (seconds)


def _convert_pt_to_onnx(pt_path: str, onnx_path: str, imgsz: int = 640) -> List[str]:
    """
    Spawn api.runtime_management._pt_onnx_converter as a short-lived subprocess.
    PyTorch / ultralytics are imported only in that child, so their footprint
    (caching allocator, global state) dies with the child instead of pinning
    memory in the waitress parent process forever.

    Returns:
        List of class name strings extracted from model.names (empty list on fallback).
    """
    logger.info(f"Spawning _pt_onnx_converter subprocess: {pt_path} → {onnx_path} (imgsz={imgsz})")

    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "api.runtime_management._pt_onnx_converter",
                "--pt", pt_path,
                "--onnx", onnx_path,
                "--imgsz", str(imgsz),
            ],
            capture_output=True,
            text=True,
            timeout=_PT_ONNX_TIMEOUT_SEC,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f".pt -> .onnx converter timed out after {_PT_ONNX_TIMEOUT_SEC}s"
        ) from exc

    # Surface child stderr in our logs regardless of outcome (it carries the
    # ultralytics/torch progress + tracebacks).
    if result.stderr:
        for line in result.stderr.rstrip().splitlines():
            logger.info("[pt_onnx] %s", line)

    if result.returncode != 0:
        # Try to extract a structured error from the last stdout line.
        err_msg = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error"
        try:
            last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
            parsed = json.loads(last)
            if isinstance(parsed, dict) and parsed.get("error"):
                err_msg = parsed["error"]
        except (ValueError, IndexError):
            pass
        raise RuntimeError(f".pt -> .onnx conversion failed: {err_msg}")

    # Parse the last stdout line (machine-readable JSON contract).
    class_names: List[str] = []
    stdout_stripped = result.stdout.strip()
    if stdout_stripped:
        try:
            last = stdout_stripped.splitlines()[-1]
            parsed = json.loads(last)
            if isinstance(parsed, dict):
                cn = parsed.get("class_names")
                if isinstance(cn, list):
                    class_names = [str(n) for n in cn]
        except (ValueError, IndexError):
            logger.warning("_pt_onnx_converter stdout did not end with a JSON line")

    if not os.path.exists(onnx_path):
        raise RuntimeError(
            f"_pt_onnx_converter reported success but {onnx_path} not found"
        )

    logger.info(f"ONNX conversion complete: {onnx_path} ({len(class_names)} class names)")
    return class_names


def _build_engine_from_onnx(onnx_path: str, engine_path: str) -> None:
    """
    Request a TensorRT .engine build from an already-exported .onnx via the
    IPC worker. The builder logic lives in
    api.runtime_management._trt_engine_builder.build_engine.
    """
    logger.info(f"Requesting TensorRT engine build via worker: {onnx_path} → {engine_path}")

    workspace_mb = int(os.environ.get("TENSORRT_WORKSPACE_MB", "256"))

    from api.runtime_management.worker_client import get_worker_client  # type: ignore

    client = get_worker_client()
    client.build_engine(onnx_path, engine_path, workspace_mb=workspace_mb)

    if not os.path.exists(engine_path):
        raise RuntimeError(
            f"Worker reported success but engine file not found: {engine_path}"
        )

    logger.info(f"TensorRT engine saved: {engine_path}")


def _remove_file_safe(path: str) -> None:
    """Remove a file, logging a warning on failure instead of raising."""
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.info(f"Removed intermediate file: {path}")
    except OSError as exc:
        logger.warning(f"Could not remove {path}: {exc}")


class ConversionService:
    """Thread-safe async conversion service."""

    def __init__(self, event_service=None) -> None:
        self._jobs: Dict[str, ConversionJob] = {}
        self._lock = threading.Lock()
        self._event_service = event_service

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def to_dict(job: ConversionJob) -> dict:
        """Serialize a job to the JSON dict the gateway returns to clients."""
        return {
            "job_id": job.job_id,
            "original_filename": job.original_filename,
            "status": job.status.value,
            "progress": job.progress,
            "message": job.message,
            "error": job.error,
            "engine_filename": job.engine_filename,
            "started_at": job.started_at,
        }

    def start_onnx_conversion(
        self,
        onnx_path: str,
        original_filename: str,
        model_directory: str,
    ) -> ConversionJob:
        """
        Enqueue an async .onnx → .engine conversion (skips the .pt → .onnx step).

        Returns the ConversionJob immediately (status=pending).
        """
        job_id = str(uuid.uuid4())
        base = os.path.splitext(original_filename)[0]
        engine_path = os.path.join(model_directory, f"{base}.engine")

        job = ConversionJob(
            job_id=job_id,
            original_filename=original_filename,
            pt_path="",          # not applicable
            onnx_path=onnx_path,
            engine_path=engine_path,
        )

        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"conversion-{job_id[:8]}",
        )
        thread.start()
        logger.info(f"ONNX conversion job {job_id} started for {original_filename}")
        return job

    def start_pt_conversion(
        self,
        pt_path: str,
        original_filename: str,
        model_directory: str,
        imgsz: int = 640,
    ) -> ConversionJob:
        """
        Enqueue an async .pt → .onnx → .engine conversion.

        Returns the ConversionJob immediately (status=pending).
        """
        job_id = str(uuid.uuid4())
        base = os.path.splitext(original_filename)[0]
        onnx_path = os.path.join(model_directory, f"{base}.onnx")
        engine_path = os.path.join(model_directory, f"{base}.engine")

        job = ConversionJob(
            job_id=job_id,
            original_filename=original_filename,
            pt_path=pt_path,
            onnx_path=onnx_path,
            engine_path=engine_path,
        )

        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, imgsz),
            daemon=True,
            name=f"conversion-{job_id[:8]}",
        )
        thread.start()
        logger.info(f"Conversion job {job_id} started for {original_filename}")
        return job

    def get_job(self, job_id: str) -> Optional[ConversionJob]:
        """Return a job by id, or ``None`` if unknown."""
        with self._lock:
            return self._jobs.get(job_id)

    def get_active_jobs(self) -> List[ConversionJob]:
        """Return all jobs that have not yet reached a terminal state."""
        terminal = {ConversionStatus.DONE, ConversionStatus.FAILED}
        with self._lock:
            return [j for j in self._jobs.values() if j.status not in terminal]

    # ------------------------------------------------------------------
    # Internal – conversion steps
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal – job status helper
    # ------------------------------------------------------------------

    def _set_status(
        self,
        job_id: str,
        status: ConversionStatus,
        progress: int,
        message: str,
        error: Optional[str] = None,
        engine_filename: Optional[str] = None,
    ) -> None:
        """Update a job's status/progress and publish a ``conversion_changed`` event."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.progress = progress
            job.message = message
            if error is not None:
                job.error = error
            if engine_filename is not None:
                job.engine_filename = engine_filename
            event_data = self.to_dict(job)
        self._publish_event(
            "conversion_changed",
            ["conversion"],
            data=event_data,
        )

    def _publish_event(self, event_type: str, keys: List[str], data: Optional[dict] = None) -> None:
        """Publish an event via the EventService (no-op if none is wired)."""
        if self._event_service is None:
            return
        try:
            self._event_service.publish(event_type, keys=keys, source="conversion", data=data)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not publish conversion event '%s': %s", event_type, exc)

    # ------------------------------------------------------------------
    # Internal – worker thread
    # ------------------------------------------------------------------

    def _run_job(self, job_id: str, imgsz: Optional[int] = None) -> None:
        """
        Worker thread for all conversion paths.

        imgsz=None  → .onnx → .engine only
        imgsz=<int> → .pt  → .onnx → .engine
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return

        try:
            # ── Step 1 (PT path only): .pt → .onnx ────────────────────
            if imgsz is not None:
                self._set_status(job_id, ConversionStatus.CONVERTING_TO_ONNX,
                                 progress=5, message="Converting .pt to ONNX…")
                class_names = _convert_pt_to_onnx(job.pt_path, job.onnx_path, imgsz)
                if class_names:
                    from api.repositories.class_labels_repository import ClassLabelsRepository
                    from api.services.model_service import ModelService
                    classes_path = ModelService.classes_file_for_model(job.engine_path)
                    ClassLabelsRepository(classes_path).save_labels(class_names)
                    logger.info(
                        f"Auto-saved {len(class_names)} class labels to {classes_path}: {class_names}"
                    )
                    self._publish_event(
                        "classes_changed",
                        ["classes"],
                        data={
                            "model": os.path.basename(job.engine_path),
                            "count": len(class_names),
                        },
                    )
                self._set_status(job_id, ConversionStatus.CONVERTING_TO_ONNX,
                                 progress=40, message="ONNX export complete. Building TensorRT engine…")
                tmp_files = [job.pt_path, job.onnx_path]
                engine_progress = 45
            else:
                tmp_files = [job.onnx_path]
                engine_progress = 10

            # ── Step 2: .onnx → .engine ───────────────────────────────
            self._set_status(job_id, ConversionStatus.CONVERTING_TO_ENGINE,
                             progress=engine_progress,
                             message="Building TensorRT .engine (this may take several minutes)…")
            _build_engine_from_onnx(job.onnx_path, job.engine_path)

            # ── Cleanup intermediate files ─────────────────────────────
            for path in tmp_files:
                _remove_file_safe(path)

            engine_filename = os.path.basename(job.engine_path)
            self._set_status(job_id, ConversionStatus.DONE, progress=100,
                             message=f"Conversion complete. Engine saved as '{engine_filename}'.",
                             engine_filename=engine_filename)
            self._publish_event(
                "models_changed",
                ["models"],
                data={"model": engine_filename},
            )
            logger.info(f"Job {job_id} completed → {engine_filename}")

        except Exception as exc:
            logger.exception(f"Job {job_id} failed: {exc}")
            self._set_status(job_id, ConversionStatus.FAILED, progress=0,
                             message="Conversion failed.", error=str(exc))
