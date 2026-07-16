"""
gRPC server for the headless inference-service.

Exposes the `DetectionControl` service (proto/inference.proto) backed by the
in-process services. It is the service's only control surface: the api-gateway
talks to it over gRPC while the processed frames cross via shared memory.

Started as a background thread from `main.py`.
"""
import json
import logging
import os
import sys
import threading
import time
from concurrent import futures

import grpc

# Generated *_pb2 / *_pb2_grpc modules do a flat `import inference_pb2`, so their
# directory must be importable. In the image the stubs are generated next to
# this file (api/proto, see Dockerfile.inference-service). For local dev they
# come from scripts/compile-proto.sh, which writes them to api-gateway/gateway/
# proto — fall back to that when the co-located dir is absent.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROTO_DIR = os.path.join(_HERE, "proto")
if not os.path.isdir(_PROTO_DIR):
    _repo_root = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
    _PROTO_DIR = os.path.join(_repo_root, "api-gateway", "gateway", "proto")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import inference_pb2 as pb          # noqa: E402
import inference_pb2_grpc as pb_grpc  # noqa: E402

logger = logging.getLogger(__name__)

LISTEN_ADDR = os.environ.get("INFERENCE_GRPC_LISTEN", "0.0.0.0:50061")
_EVENT_KEEPALIVE_S = 15.0
_STATS_INTERVAL_S = 0.25


def _unimplemented(context, what: str):
    """Mark the current RPC ``UNIMPLEMENTED`` with a placeholder message."""
    context.set_code(grpc.StatusCode.UNIMPLEMENTED)
    context.set_details(f"{what} not implemented yet (pending gateway cutover)")


class DetectionControlServicer(pb_grpc.DetectionControlServicer):
    """`DetectionControl` RPCs — detection lifecycle, tuning, trigger/counter
    and the event/stats telemetry streams. Thin adapters over the in-process
    detection/stats/event services."""

    def __init__(self, application):
        self._app = application

    @property
    def _det(self):
        """The shared DetectionService."""
        return self._app.detection_service

    @property
    def _stats(self):
        """The shared StatsService."""
        return self._app.stats_service

    @property
    def _events(self):
        """The shared EventService."""
        return self._app.event_service

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def Start(self, request, context):
        """RPC: start the detection loop."""
        try:
            self._det.start()
            return pb.Result(success=True, message="Detection started")
        except Exception as exc:  # noqa: BLE001
            return pb.Result(success=False, message=str(exc))

    def Stop(self, request, context):
        """RPC: stop the detection loop."""
        try:
            self._det.stop()
            return pb.Result(success=True, message="Detection stopped")
        except Exception as exc:  # noqa: BLE001
            return pb.Result(success=False, message=str(exc))

    def GetStatus(self, request, context):
        """RPC: return run state, active model, thresholds, runtime and stats."""
        det = self._det
        cfg = det.config
        s = self._stats.get_stats()
        return pb.StatusResponse(
            is_running=bool(det.is_running),
            model=os.path.basename(cfg.MODEL_PATH or ""),
            confidence_threshold=float(cfg.CONFIDENCE_THRESHOLD),
            overlay_threshold=float(cfg.OVERLAY_THRESHOLD),
            acceleration_type=str(det.acceleration_type()),
            runtime_type=str(det.runtime_api()),
            trigger_enabled=bool(det.get_trigger_status()),
            detection_count=int(det.get_detection_count()),
            stats=_stats_pb(s),
            camera_connected=bool(self._app.video_service.camera_connected()),
        )

    # ── tuning ────────────────────────────────────────────────────────────────

    def SetThreshold(self, request, context):
        """RPC: set the confidence threshold (0–1)."""
        ok = self._det.set_confidence_threshold(request.threshold)
        return pb.Result(success=bool(ok),
                         message="Threshold updated" if ok else "Threshold must be between 0 and 1")

    def SetOverlayThreshold(self, request, context):
        """RPC: set the IoU/NMS overlay threshold (0–1) and persist it."""
        ok = self._det.config.set_overlay_threshold(request.threshold)
        if ok:
            ms = getattr(self._app, "model_settings_service", None)
            if ms is not None:
                try:
                    ms.save()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("persist overlay threshold failed: %s", exc)
        return pb.Result(success=bool(ok),
                         message="Overlay threshold updated" if ok else "Threshold must be between 0 and 1")

    # ── trigger / counter / stats ───────────────────────────────────────────────

    def EnableTrigger(self, request, context):
        """RPC: enable frame processing (trigger gate on)."""
        self._det.enable_trigger()
        return pb.Result(success=True, message="Trigger enabled")

    def DisableTrigger(self, request, context):
        """RPC: freeze the last processed frame (trigger gate off)."""
        self._det.disable_trigger()
        return pb.Result(success=True, message="Trigger disabled")

    def GetCounter(self, request, context):
        """RPC: return the accumulated detection count and trigger state."""
        return pb.CounterResponse(
            count=int(self._det.get_detection_count()),
            trigger_enabled=bool(self._det.get_trigger_status()),
        )

    def ResetCounter(self, request, context):
        """RPC: reset the detection counter."""
        self._det.reset_detection_count()
        return pb.Result(success=True, message="Counter reset")

    def ResetStats(self, request, context):
        """RPC: reset the performance statistics."""
        self._stats.reset()
        return pb.Result(success=True, message="Stats reset")

    def Snapshot(self, request, context):
        """RPC: return the current detections (optionally with the frame) as JSON."""
        # The hub polls this ~1x/s: it doubles as the hub-is-online heartbeat
        # for the offline detection buffer. Only hub pulls count — the Flow
        # detection node (and any local script) polls the same snapshot, and
        # treating those as hub contact would keep the buffer disarmed forever.
        if request.hub_pull:
            self._app.detection_buffer.note_snapshot_pull()
        # Thin: DetectionService owns the snapshot logic; carry it as a JSON
        # blob the gateway relays verbatim (mirrors config/camera/system).
        snap = self._det.detections_snapshot(
            bool(request.include_frame), bool(request.include_raw_frame)
        )
        return pb.SnapshotResponse(json=json.dumps(snap))

    def ListBacklog(self, request, context):
        """RPC: one page of offline-buffered detection records, oldest first.

        Deliberately does NOT count as a hub pull: changes that happen during
        a long drain are buffered and picked up on the next cycle.
        """
        page = self._app.detection_buffer.list_backlog(int(request.limit))
        return pb.BacklogResponse(json=json.dumps(page))

    def AckBacklog(self, request, context):
        """RPC: delete buffered records the hub confirmed persisting (idempotent)."""
        n = self._app.detection_buffer.ack(list(request.ids))
        return pb.Result(success=True, message=f"{n} records acknowledged")

    # ── model activation (driven by the model-service migration) ─────────────────

    def ReloadModel(self, request, context):
        """RPC (not implemented): reload the live model."""
        _unimplemented(context, "ReloadModel")
        return pb.Result(success=False, message="not implemented")

    def SetDetectionAreas(self, request, context):
        """RPC (not implemented): replace the detection areas."""
        _unimplemented(context, "SetDetectionAreas")
        return pb.Result(success=False, message="not implemented")

    def SetSettings(self, request, context):
        """RPC (not implemented): push model settings."""
        _unimplemented(context, "SetSettings")
        return pb.Result(success=False, message="not implemented")

    # ── telemetry streams ────────────────────────────────────────────────────────

    def StreamEvents(self, request, context):
        """RPC (server stream): emit a snapshot then each invalidation event.

        Keepalive-bounded: ``wait_for_changes`` returns periodically so the
        stream stays responsive to client cancellation.
        """
        version, snap = self._events.snapshot()
        yield _event_pb(snap)
        last = version
        while context.is_active():
            new_version, events, _sv, _st, changed = self._events.wait_for_changes(
                last, None, _EVENT_KEEPALIVE_S
            )
            if changed:
                for ev in events:
                    yield _event_pb(ev)
            last = new_version

    def StreamStats(self, request, context):
        """RPC (server stream): emit the live stats every ``_STATS_INTERVAL_S``."""
        while context.is_active():
            s = self._stats.get_stats()
            yield pb.StatsUpdate(version=0, stats=_stats_pb(s))
            time.sleep(_STATS_INTERVAL_S)


class ModelControlServicer(pb_grpc.ModelControlServicer):
    """Model lifecycle. Stays inference-side because SelectModel reloads the
    live detector (activate_model)."""

    def __init__(self, application):
        self._app = application

    @property
    def _models(self):
        """The shared ModelService."""
        return self._app.model_service

    @property
    def _conv(self):
        """The shared ConversionService."""
        return self._app.conversion_service

    def ListModels(self, request, context):
        """RPC: list available models (name, path, size, modified, active)."""
        out = []
        for m in self._models.list_models():
            out.append(pb.ModelInfo(
                name=m.name, path=getattr(m, "path", ""), size=int(getattr(m, "size", 0) or 0),
                modified=float(getattr(m, "modified", 0.0) or 0.0),
                is_active=bool(getattr(m, "is_active", False)),
            ))
        return pb.ModelList(models=out)

    def SelectModel(self, request, context):
        """RPC: activate a model by name (reloads the live detector)."""
        success, result, _was_running = self._models.activate_model(request.name)
        return pb.Result(success=bool(success), message=str(result))

    def DeleteModel(self, request, context):
        """RPC: delete a model by name."""
        success, message = self._models.delete_model(request.name)
        return pb.Result(success=bool(success), message=str(message))

    def ListConversions(self, request, context):
        """RPC: list active `.pt`→`.engine` conversion jobs."""
        return pb.ConversionList(jobs=[_conversion_pb(j) for j in self._conv.get_active_jobs()])

    def GetConversion(self, request, context):
        """RPC: return one conversion job by id (NOT_FOUND if unknown)."""
        job = self._conv.get_job(request.job_id)
        if job is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"No conversion job '{request.job_id}'")
            return pb.ConversionJob()
        return _conversion_pb(job)

    def UploadModel(self, request_iterator, context):
        """RPC (client stream): assemble an uploaded model and save/convert it.

        The first message carries the metadata, the rest are file chunks.
        ModelService owns the save/convert/activate decision; its result and the
        intended HTTP status are carried back as a JSON blob for the gateway.
        """
        # Thin: assemble the client-streamed chunks, then ModelService owns the
        # save/convert/activate decision. Carry its result as a JSON blob the
        # gateway relays verbatim, plus the intended HTTP status.
        meta = None
        buf = bytearray()
        for msg in request_iterator:
            which = msg.WhichOneof("data")
            if which == "meta":
                meta = msg.meta
            elif which == "chunk":
                buf.extend(msg.chunk)
        if meta is None or not meta.filename:
            return pb.UploadResult(
                ok=False, http_status=400,
                json=json.dumps({"error": "Missing upload metadata"}),
            )
        imgsz = int(meta.imgsz) or 640
        body, status = self._models.process_upload(meta.filename, _BytesFile(bytes(buf)), imgsz)
        return pb.UploadResult(ok=(200 <= status < 300), http_status=int(status),
                               json=json.dumps(body))

    def DownloadModel(self, request, context):
        """RPC (server stream): stream a model file's bytes in ~1 MiB chunks."""
        path = self._models.model_file_path(request.name)
        if not path:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Model '{request.name}' not found")
            return
        try:
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    yield pb.ModelFileChunk(chunk=chunk)
        except OSError as exc:
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to read model '{request.name}': {exc}")
            return

class ManagementControlServicer(pb_grpc.ManagementControlServicer):
    """Classes + detection-areas: per-model state consumed by the live detector,
    so it stays inference-side. Area ops return the full state JSON (mirroring
    the REST controller's state response) for the gateway to relay verbatim."""

    def __init__(self, application):
        self._app = application

    # ── classes (current model's sibling .txt) ────────────────────────────────
    def _repo(self):
        """Build a ClassLabelsRepository for the current model's labels file."""
        from api.repositories import ClassLabelsRepository
        return ClassLabelsRepository(self._app.config.CLASSES_FILE_PATH)

    def GetClasses(self, request, context):
        """RPC: list the current model's class labels."""
        return pb.ClassList(classes=list(self._repo().load_labels()))

    def SetClasses(self, request, context):
        """RPC: replace the current model's class labels."""
        ok = self._repo().save_labels(list(request.classes))
        return pb.Result(success=bool(ok),
                         message="Classes updated" if ok else "Failed to save classes")

    def ClearClasses(self, request, context):
        """RPC: clear custom labels (revert to the model default)."""
        ok = self._repo().save_labels([])
        return pb.Result(success=bool(ok),
                         message="Classes cleared" if ok else "Failed to clear classes")

    # ── config (thin: ConfigService owns the logic) ──────────────────────────
    def GetConfig(self, request, context):
        """RPC: return the current configuration as JSON."""
        return pb.ConfigJson(json=json.dumps(self._app.config_service.get_config()))

    def UpdateConfig(self, request, context):
        """RPC: apply a configuration update from a JSON body."""
        try:
            data = json.loads(request.json or "{}")
        except ValueError as exc:
            return pb.Result(success=False, message=f"Invalid JSON: {exc}")
        ok, message = self._app.config_service.update_config(data)
        return pb.Result(success=ok, message=message)

    # ── camera (thin: VideoService owns the logic) ───────────────────────────
    def GetCamera(self, request, context):
        """RPC: list V4L2 devices + current camera config as JSON."""
        return pb.ConfigJson(json=json.dumps(self._app.video_service.list_camera_devices()))

    def UpdateCamera(self, request, context):
        """RPC: apply a camera update (via SHM) and persist it on success."""
        try:
            data = json.loads(request.json or "{}")
        except ValueError as exc:
            return pb.Result(success=False, message=f"Invalid JSON: {exc}")
        ok, message, _status = self._app.video_service.apply_camera_update(data)
        if ok:
            ms = getattr(self._app, "model_settings_service", None)
            if ms is not None:
                try:
                    ms.save()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("persist camera config failed: %s", exc)
        return pb.Result(success=ok, message=message)

    # System metrics moved to the os hardware agent (HardwareService.GetSystemStatus);
    # the gateway calls it there now.

    # ── detection areas ────────────────────────────────────────────────────────
    @property
    def _areas(self):
        """The shared DetectionAreaService."""
        return self._app.detection_area_service

    def _state(self, ok: bool = True) -> "pb.AreaResult":
        """Wrap the full areas state as an ``AreaResult`` for the gateway."""
        state = {"areas": [a.to_dict() for a in self._areas.list()]}
        return pb.AreaResult(ok=ok, state_json=json.dumps(state))

    def ListAreas(self, request, context):
        """RPC: return all detection areas."""
        return self._state(True)

    def CreateArea(self, request, context):
        """RPC: create a new (centered, editing) detection area."""
        self._areas.add()
        return self._state(True)

    def DeleteArea(self, request, context):
        """RPC: delete a detection area by id."""
        return self._state(self._areas.delete(request.area_id))

    def SaveArea(self, request, context):
        """RPC: commit an area (leave editing mode; filter stays active)."""
        return self._state(self._areas.save(request.area_id) is not None)

    def EditArea(self, request, context):
        """RPC: promote a saved area back to editing mode."""
        return self._state(self._areas.edit(request.area_id) is not None)

    def DiscardArea(self, request, context):
        """RPC: discard the editing area."""
        return self._state(self._areas.discard(request.area_id))

    def SetAreaShape(self, request, context):
        """RPC: set an area's shape (rectangle/circle); no-op on invalid shape."""
        from api.services.detection_area_service import VALID_SHAPES
        if request.shape not in VALID_SHAPES:
            return pb.AreaResult(ok=False, state_json=self._state(True).state_json)
        return self._state(self._areas.set_shape(request.area_id, request.shape) is not None)

    def AreaCommand(self, request, context):
        """RPC: apply a move/resize command to an area; no-op on invalid action."""
        from api.services.detection_area_service import VALID_ACTIONS
        if request.action not in VALID_ACTIONS:
            return pb.AreaResult(ok=False, state_json=self._state(True).state_json)
        return self._state(self._areas.apply_command(request.area_id, request.action) is not None)

    # ── GPU handover (training-service) ───────────────────────────────────────

    def ReleaseRuntime(self, request, context):
        """RPC: release the GPU runtime so the training-service can use it.

        Refuses while a model conversion is in progress; otherwise stops
        detection, releases the TensorRT workers, and publishes a status event.
        """
        try:
            if self._app.conversion_service.get_active_jobs():
                return pb.Result(
                    success=False,
                    message="A model conversion is in progress; try again when it finishes",
                )
            self._app.detection_service.stop()
            from api.runtime_management.worker_client import release_all_workers
            release_all_workers()
            self._app.event_service.publish(
                "runtime_changed", keys=["status"], data={"runtime_released": True}
            )
            return pb.Result(success=True, message="Runtime released")
        except Exception as exc:  # noqa: BLE001
            return pb.Result(success=False, message=str(exc))

    def ResumeRuntime(self, request, context):
        """RPC: re-initialise and resume the inference runtime after training."""
        try:
            det = self._app.detection_service
            if not det.is_running:
                det.initialize()
                det.start()
            self._app.event_service.publish(
                "runtime_changed", keys=["status"], data={"runtime_released": False}
            )
            return pb.Result(success=True, message="Runtime resumed")
        except Exception as exc:  # noqa: BLE001
            return pb.Result(success=False, message=str(exc))


class _BytesFile:
    """Adapts in-memory bytes to the ``.save(path)`` interface
    ModelService.save_model expects (Flask FileStorage over HTTP). Lets the
    gRPC client-streamed upload reuse the exact same service path."""

    def __init__(self, data: bytes):
        self._data = data

    def save(self, path: str) -> None:
        """Write the buffered bytes to *path*."""
        with open(path, "wb") as f:
            f.write(self._data)


def _conversion_pb(job) -> "pb.ConversionJob":
    """Convert a conversion-job object to a ``ConversionJob`` message."""
    status = getattr(job, "status", "")
    return pb.ConversionJob(
        job_id=str(getattr(job, "job_id", "")),
        original_filename=str(getattr(job, "original_filename", "")),
        status=str(getattr(status, "value", status) or ""),
        progress=int(getattr(job, "progress", 0) or 0),
        message=str(getattr(job, "message", "") or ""),
        error=str(getattr(job, "error", "") or ""),
        engine_filename=str(getattr(job, "engine_filename", "") or ""),
        started_at=float(getattr(job, "started_at", 0.0) or 0.0),
    )


def _stats_pb(s) -> "pb.Stats":
    """Convert a stats object to a ``Stats`` message."""
    return pb.Stats(
        fps=float(getattr(s, "fps", 0.0) or 0.0),
        inference_time=float(getattr(s, "inference_time", 0.0) or 0.0),
        detections=int(getattr(s, "detections", 0) or 0),
        frames_with_detections=int(getattr(s, "frames_with_detections", 0) or 0),
    )


def _event_pb(ev: dict) -> "pb.Event":
    """Convert an event dict to an ``Event`` message (data carried as JSON)."""
    return pb.Event(
        version=int(ev.get("version", 0)),
        type=str(ev.get("type", "")),
        timestamp=float(ev.get("timestamp", 0.0)),
        source=str(ev.get("source", "")),
        keys=list(ev.get("keys", []) or []),
        data=json.dumps(ev.get("data", {}) or {}),
    )


def serve_grpc(application) -> None:
    """Start the DetectionControl gRPC server in a daemon thread (non-blocking)."""
    def _run() -> None:
        """Thread body: build, register, start the server and block on it."""
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
        pb_grpc.add_DetectionControlServicer_to_server(
            DetectionControlServicer(application), server
        )
        pb_grpc.add_ModelControlServicer_to_server(
            ModelControlServicer(application), server
        )
        pb_grpc.add_ManagementControlServicer_to_server(
            ManagementControlServicer(application), server
        )
        server.add_insecure_port(LISTEN_ADDR)
        server.start()
        logger.info("Inference DetectionControl gRPC server listening on %s", LISTEN_ADDR)
        server.wait_for_termination()

    threading.Thread(target=_run, daemon=True, name="inference-grpc").start()
