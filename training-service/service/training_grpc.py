"""gRPC server for the training-service (proto/training.proto, :50071).

Thin servicer over the dataset/capture/SAM/training services; the api-gateway
is the only client and relays REST↔gRPC plus the event stream onto its SSE bus
(same shape as the inference-service's inference_grpc.py).
"""
import json
import logging
import os
import subprocess
import sys
import threading
from concurrent import futures

import grpc

# Generated *_pb2 / *_pb2_grpc modules do a flat `import training_pb2`, so their
# directory must be importable. In the image the stubs are generated next to
# this file (service/proto, see Dockerfile.training-service). For local dev they
# come from scripts/compile-proto.sh, which writes them to api-gateway/gateway/
# proto — fall back to that when the co-located dir is absent.
_HERE = os.path.dirname(os.path.abspath(__file__))
_PROTO_DIR = os.path.join(_HERE, "proto")
if not os.path.isdir(_PROTO_DIR):
    _repo_root = os.path.abspath(os.path.join(_HERE, os.pardir, os.pardir))
    _PROTO_DIR = os.path.join(_repo_root, "api-gateway", "gateway", "proto")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import training_pb2 as pb            # noqa: E402
import training_pb2_grpc as pb_grpc  # noqa: E402

import cv2                           # noqa: E402
import numpy as np                   # noqa: E402

from .capture_service import corners_to_letterbox, letterbox_square  # noqa: E402
from .dataset_service import Box, DatasetError, NamedBox  # noqa: E402

logger = logging.getLogger(__name__)

_EVENT_KEEPALIVE_S = 15.0


def _image_pb(entry) -> "pb.ImageInfo":
    """Convert a dataset image entry to an ``ImageInfo`` message."""
    return pb.ImageInfo(
        image_id=entry.image_id,
        created_at=float(entry.created_at),
        labeled=bool(entry.labeled),
        box_count=int(entry.box_count),
        replica=bool(getattr(entry, "replica", False)),
    )


def _job_pb(job) -> "pb.TrainingJob":
    """Convert a training-job object to a ``TrainingJob`` message."""
    return pb.TrainingJob(
        job_id=job.job_id,
        status=job.status,
        progress=int(job.progress),
        epoch=int(job.epoch),
        total_epochs=int(job.total_epochs),
        message=job.message,
        error=job.error,
        model_name=job.model_name,
        conversion_job_id=job.conversion_job_id,
        metrics_json=json.dumps(job.metrics or {}),
        started_at=float(job.started_at),
        dataset_id=job.dataset_id,
        result_weights_id=job.result_weights_id,
        federated=bool(job.federated),
    )


def _meta_pb(meta: dict) -> "pb.DatasetMeta":
    """Convert a dataset metadata dict to a ``DatasetMeta`` message."""
    return pb.DatasetMeta(
        dataset_id=meta["dataset_id"],
        name=meta["name"],
        created_at=float(meta["created_at"]),
        cover_image_id=meta["cover_image_id"],
        image_count=int(meta["image_count"]),
        labeled_count=int(meta["labeled_count"]),
        class_count=int(meta["class_count"]),
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


class TrainingControlServicer(pb_grpc.TrainingControlServicer):
    """`TrainingControl` RPCs — datasets, labeling, SAM3 and the training job.

    Thin adapters over the in-process training/dataset/SAM services; dataset
    images travel as unary bytes (small JPEGs), not over SHM.
    """

    def __init__(self, application):
        self._app = application

    @property
    def _registry(self):
        return self._app.dataset_registry

    def _ds(self, dataset_id: str):
        """Resolve a dataset or raise DatasetError (mapped per-handler)."""
        return self._registry.get(dataset_id)

    # ── dataset registry ──────────────────────────────────────────────────────

    def ListDatasets(self, request, context):
        """RPC: list datasets."""
        return pb.DatasetList(datasets=[_meta_pb(m) for m in self._registry.list()])

    def CreateDataset(self, request, context):
        """RPC: create dataset."""
        try:
            return _meta_pb(self._registry.create(request.name))
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.DatasetMeta()

    def RenameDataset(self, request, context):
        """RPC: rename dataset."""
        try:
            return _meta_pb(self._registry.rename(request.dataset_id, request.name))
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.DatasetMeta()

    def DeleteDataset(self, request, context):
        """RPC: delete dataset."""
        try:
            self._ds(request.dataset_id)  # map unknown ids to NOT_FOUND
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.Result()
        try:
            self._registry.delete(request.dataset_id)
            return pb.Result(success=True, message="Dataset deleted")
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.Result()

    def SetDatasetCover(self, request, context):
        """RPC: set dataset cover."""
        try:
            ds = self._ds(request.dataset_id)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.Result()

        if ds.frozen:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details("Dataset is locked while a training job is running")
            return pb.Result()

        try:
            ds.set_cover(request.image_id)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.Result()

        self._app.event_service.publish(
            "datasets_changed", keys=["datasets"],
            data={"dataset_id": request.dataset_id,
                  "cover_image_id": request.image_id},
        )
        return pb.Result(success=True, message="Cover set")

    def UploadDataset(self, request_iterator, context):
        """RPC: upload dataset."""
        first = next(request_iterator, None)
        if first is None or first.WhichOneof("payload") != "meta":
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("First upload message must carry the dataset meta")
            return pb.DatasetUploadResult()
        name = first.meta.name
        budget = self._app.config.MAX_DATASET_UPLOAD_MB * 1024 * 1024
        zip_path = os.path.join(self._app.config.datasets_dir,
                                f".upload-{os.urandom(8).hex()}.zip")
        try:
            total = 0
            with open(zip_path, "wb") as f:
                for msg in request_iterator:
                    if msg.WhichOneof("payload") != "chunk":
                        raise DatasetError("Unexpected non-chunk upload message")
                    total += len(msg.chunk)
                    if total > budget:
                        raise DatasetError(
                            f"Dataset ZIP exceeds the "
                            f"{self._app.config.MAX_DATASET_UPLOAD_MB} MB limit"
                        )
                    f.write(msg.chunk)
            meta = self._registry.import_zip(name, zip_path)
            return pb.DatasetUploadResult(success=True,
                                          message="Dataset imported",
                                          dataset=_meta_pb(meta))
        except DatasetError as exc:
            # The message is user-facing (shown by the frontend), but keep it
            # in the service log too so failed imports are diagnosable.
            logger.warning("Dataset import '%s' rejected: %s", name, exc)
            return pb.DatasetUploadResult(success=False, message=str(exc))
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def ExportDataset(self, request, context):
        """RPC: export dataset."""
        try:
            dataset = self._ds(request.dataset_id)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return
        zip_path = os.path.join(self._app.config.datasets_dir,
                                f".export-{os.urandom(8).hex()}.zip")
        try:
            count = dataset.export_zip(zip_path)
            logger.info("Exporting dataset %s: %d images, %d bytes",
                        request.dataset_id, count, os.path.getsize(zip_path))
            with open(zip_path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    yield pb.DatasetExportChunk(chunk=chunk)
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

    # ── federated training ────────────────────────────────────────────────────

    def ExportDatasetShard(self, request, context):
        """RPC: export one deterministic IID shard of a dataset."""
        if not (2 <= request.num_shards <= 16) or \
                request.shard_index >= request.num_shards:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("num_shards must be 2..16 and shard_index < num_shards")
            return
        try:
            dataset = self._ds(request.dataset_id)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return
        zip_path = os.path.join(self._app.config.datasets_dir,
                                f".export-{os.urandom(8).hex()}.zip")
        try:
            count = dataset.export_zip(
                zip_path, num_shards=int(request.num_shards),
                shard_index=int(request.shard_index), seed=request.seed,
            )
            logger.info("Exporting shard %d/%d of dataset %s: %d images, %d bytes",
                        request.shard_index, request.num_shards,
                        request.dataset_id, count, os.path.getsize(zip_path))
            with open(zip_path, "rb") as f:
                while True:
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    yield pb.DatasetExportChunk(chunk=chunk)
        finally:
            if os.path.exists(zip_path):
                os.remove(zip_path)

    def UploadWeights(self, request_iterator, context):
        """RPC: upload weights."""
        first = next(request_iterator, None)
        if first is None or first.WhichOneof("payload") != "meta":
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("First upload message must carry the weights meta")
            return pb.WeightsUploadResult()
        name = first.meta.name

        def _chunks():
            """Chunks."""
            for msg in request_iterator:
                if msg.WhichOneof("payload") != "chunk":
                    raise DatasetError("Unexpected non-chunk upload message")
                yield msg.chunk

        try:
            weights_id, size = self._app.weights_store.save_stream(_chunks())
            logger.info("Weights '%s' stashed as %s (%d bytes)",
                        name, weights_id, size)
            return pb.WeightsUploadResult(success=True, message="Weights stashed",
                                          weights_id=weights_id, size=size)
        except DatasetError as exc:
            logger.warning("Weights upload '%s' rejected: %s", name, exc)
            return pb.WeightsUploadResult(success=False, message=str(exc))

    def DownloadWeights(self, request, context):
        """RPC: download weights."""
        try:
            path = self._app.weights_store.path(request.weights_id)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1 << 20)
                if not chunk:
                    break
                yield pb.WeightsDownloadChunk(chunk=chunk)

    def AverageWeights(self, request, context):
        """RPC: average stashed checkpoints (FedAvg, CPU child process)."""
        ids = list(request.weights_ids)
        if len(ids) < 2:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("Averaging needs at least two weights ids")
            return pb.AverageResult()
        try:
            paths = [self._app.weights_store.path(i) for i in ids]
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.AverageResult()

        out_path = os.path.join(self._app.config.weights_dir,
                                f".avg-{os.urandom(8).hex()}.pt")
        env = os.environ.copy()
        env["PYTHONPATH"] = "/app/training-service"
        cmd = [sys.executable, "-m", "service._weights_averager",
               "--inputs", *paths, "--output", out_path]
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True,
                                  text=True, timeout=240)
            payload = {}
            for line in reversed(proc.stdout.strip().splitlines() or [""]):
                try:
                    payload = json.loads(line)
                    break
                except ValueError:
                    continue
            if proc.returncode != 0 or not payload.get("done"):
                message = payload.get("error") or \
                    f"Averager exited with code {proc.returncode}"
                logger.warning("Weights averaging failed: %s", message)
                return pb.AverageResult(success=False, message=message)
            weights_id = self._app.weights_store.stash_file(out_path)
            logger.info("Averaged %d checkpoints into %s", len(ids), weights_id)
            return pb.AverageResult(success=True, message="Checkpoints averaged",
                                    weights_id=weights_id)
        except subprocess.TimeoutExpired:
            return pb.AverageResult(success=False, message="Averaging timed out")
        finally:
            if os.path.exists(out_path):
                os.remove(out_path)

    def DeleteWeights(self, request, context):
        """RPC: delete weights."""
        try:
            self._app.weights_store.delete(request.weights_id)
        except DatasetError as exc:
            return pb.Result(success=False, message=str(exc))
        return pb.Result(success=True, message="Weights deleted")

    # ── dataset / capture ─────────────────────────────────────────────────────

    def GetDataset(self, request, context):
        """RPC: get dataset."""
        try:
            info = self._ds(request.dataset_id).info()
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.DatasetInfo()
        return pb.DatasetInfo(
            image_count=info["image_count"],
            labeled_count=info["labeled_count"],
            classes=info["classes"],
            min_images=info["min_images"],
            dataset_id=info["dataset_id"],
            name=info["name"],
            cover_image_id=info["cover_image_id"],
        )

    def CaptureImage(self, request, context):
        """RPC: capture image."""
        try:
            dataset = self._ds(request.dataset_id)
            jpeg = self._app.capture_service.capture_letterboxed()
            if jpeg is None:
                context.set_code(grpc.StatusCode.UNAVAILABLE)
                context.set_details("No camera frame available")
                return pb.ImageInfo()
            entry = dataset.add_image(jpeg)
            self._app.event_service.publish(
                "dataset_changed", keys=["dataset"],
                data={"dataset_id": request.dataset_id, "image_id": entry.image_id},
            )
            return _image_pb(entry)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.ImageInfo()

    def AddDatasetImage(self, request, context):
        """RPC: add an externally captured, pre-labeled image to a dataset."""
        try:
            dataset = self._ds(request.dataset_id)
            img = cv2.imdecode(
                np.frombuffer(request.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if img is None:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("Body is not a decodable image")
                return pb.ImageInfo()
            src_h, src_w = img.shape[:2]
            size = self._app.config.IMG_SIZE
            boxed = letterbox_square(img, size)
            ok, buf = cv2.imencode(".jpg", boxed, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if not ok:
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Failed to encode the letterboxed image")
                return pb.ImageInfo()
            boxes = [
                NamedBox(b.class_name,
                         *corners_to_letterbox(b.x1, b.y1, b.x2, b.y2,
                                               src_w, src_h, size))
                for b in request.boxes
            ]
            entry = dataset.add_labeled_image(buf.tobytes(), boxes)
            self._app.event_service.publish(
                "dataset_changed", keys=["dataset"],
                data={"dataset_id": request.dataset_id, "image_id": entry.image_id},
            )
            return _image_pb(entry)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.ImageInfo()

    def ListImages(self, request, context):
        """RPC: list images."""
        try:
            entries = self._ds(request.dataset_id).list_images()
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.ImageList()
        return pb.ImageList(images=[_image_pb(e) for e in entries])

    def GetImage(self, request, context):
        """RPC: get image."""
        try:
            data = self._ds(request.dataset_id).get_image_bytes(request.image_id)
            size = self._app.config.IMG_SIZE
            return pb.ImageBlob(image_id=request.image_id, jpeg=data,
                                width=size, height=size)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.ImageBlob()

    def DeleteImage(self, request, context):
        """RPC: delete image."""
        try:
            self._ds(request.dataset_id).delete_image(request.image_id)
            self._app.event_service.publish(
                "dataset_changed", keys=["dataset"],
                data={"dataset_id": request.dataset_id, "deleted": request.image_id},
            )
            return pb.Result(success=True, message="Image deleted")
        except DatasetError as exc:
            return pb.Result(success=False, message=str(exc))

    def ReplicateImage(self, request, context):
        """RPC: replicate a labeled image (image + labels) `count` times."""
        try:
            n = self._ds(request.dataset_id).replicate_image(
                request.image_id, request.count)
            self._app.event_service.publish(
                "dataset_changed", keys=["dataset"],
                data={"dataset_id": request.dataset_id,
                      "replicated": request.image_id, "count": n},
            )
            return pb.Result(success=True, message=f"{n} replicas created")
        except DatasetError as exc:
            return pb.Result(success=False, message=str(exc))

    # ── labels ────────────────────────────────────────────────────────────────

    def GetLabels(self, request, context):
        """RPC: get labels."""
        try:
            boxes = self._ds(request.dataset_id).get_labels(request.image_id)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.Labels()
        return pb.Labels(
            image_id=request.image_id,
            dataset_id=request.dataset_id,
            boxes=[pb.Box(class_id=b.class_id, cx=b.cx, cy=b.cy, w=b.w, h=b.h)
                   for b in boxes],
        )

    def SetLabels(self, request, context):
        """RPC: set labels."""
        try:
            self._ds(request.dataset_id).set_labels(
                request.image_id,
                [Box(b.class_id, b.cx, b.cy, b.w, b.h) for b in request.boxes],
            )
            return pb.Result(success=True, message="Labels saved")
        except DatasetError as exc:
            return pb.Result(success=False, message=str(exc))

    # ── classes ───────────────────────────────────────────────────────────────

    def _classes_result(self, context, dataset_id, fn) -> "pb.ClassList":
        """Run a classes mutation *fn* and return the dataset's class list."""
        try:
            dataset = self._ds(dataset_id)
            classes = fn(dataset)
            self._app.event_service.publish(
                "dataset_changed", keys=["dataset"],
                data={"dataset_id": dataset_id, "classes": classes},
            )
            return pb.ClassList(classes=classes)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.ClassList()

    def GetClasses(self, request, context):
        """RPC: get classes."""
        try:
            classes = self._ds(request.dataset_id).get_classes()
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(str(exc))
            return pb.ClassList()
        return pb.ClassList(classes=classes)

    def AddClass(self, request, context):
        """RPC: add class."""
        return self._classes_result(
            context, request.dataset_id, lambda ds: ds.add_class(request.name)
        )

    def RenameClass(self, request, context):
        """RPC: rename class."""
        return self._classes_result(
            context, request.dataset_id,
            lambda ds: ds.rename_class(request.index, request.name),
        )

    def RemoveClass(self, request, context):
        """RPC: remove class."""
        return self._classes_result(
            context, request.dataset_id, lambda ds: ds.remove_class(request.index)
        )

    # ── SAM ───────────────────────────────────────────────────────────────────

    def GetSamStatus(self, request, context):
        """RPC: get sam status."""
        s = self._app.sam_service.status()
        return pb.SamStatus(available=s["available"], loaded=s["loaded"],
                            message=s["message"])

    def LoadSam(self, request, context):
        """RPC: load sam."""
        if self._app.training_service.is_active():
            return pb.Result(success=False,
                             message="Cannot load SAM while training is running")
        try:
            self._app.sam_service.load()
            return pb.Result(success=True, message="SAM loaded")
        except Exception as exc:  # noqa: BLE001
            return pb.Result(success=False, message=str(exc))

    def UnloadSam(self, request, context):
        """RPC: unload sam."""
        try:
            self._app.sam_service.unload()
            return pb.Result(success=True, message="SAM unloaded")
        except Exception as exc:  # noqa: BLE001
            return pb.Result(success=False, message=str(exc))

    def SamSegment(self, request, context):
        """RPC: sam segment."""
        if self._app.training_service.is_active():
            return pb.SamResult(success=False,
                                message="Cannot segment while training is running")
        try:
            image_path = self._ds(request.dataset_id)._image_path(request.image_id)
            if not os.path.exists(image_path):
                return pb.SamResult(success=False,
                                    message=f"Image '{request.image_id}' not found")
            points = [
                {"x": p.x, "y": p.y, "positive": p.positive}
                for p in request.points
            ]
            boxes, scores = self._app.sam_service.segment(
                image_path, request.text_prompt, points,
                threshold=request.threshold,
            )
            return pb.SamResult(
                success=True,
                boxes=[pb.Box(cx=b["cx"], cy=b["cy"], w=b["w"], h=b["h"])
                       for b in boxes],
                scores=[float(s) for s in scores],
            )
        except Exception as exc:  # noqa: BLE001
            return pb.SamResult(success=False, message=str(exc))

    # ── training ──────────────────────────────────────────────────────────────

    def StartTraining(self, request, context):
        """RPC: start training."""
        try:
            job = self._app.training_service.start(
                request.dataset_id, request.model_name,
                epochs=int(request.epochs), batch=int(request.batch),
                patience=int(request.patience),
                initial_weights_id=request.initial_weights_id,
                federated=bool(request.federated),
            )
            return _job_pb(job)
        except DatasetError as exc:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(str(exc))
            return pb.TrainingJob()

    def GetTraining(self, request, context):
        """RPC: get training."""
        return _job_pb(self._app.training_service.get_job())

    def CancelTraining(self, request, context):
        """RPC: cancel training."""
        ok = self._app.training_service.cancel()
        return pb.Result(success=ok,
                         message="Cancel requested" if ok else "No training job running")

    def FinishTraining(self, request, context):
        """RPC: finish training."""
        ok = self._app.training_service.finish_early()
        return pb.Result(success=ok,
                         message="Finishing early" if ok else "No training job running")

    # ── telemetry ─────────────────────────────────────────────────────────────

    def StreamEvents(self, request, context):
        """RPC: stream events."""
        events = self._app.event_service
        version, snap = events.snapshot()
        yield _event_pb(snap)
        last = version
        while context.is_active():
            new_version, evs, changed = events.wait_for_changes(last, _EVENT_KEEPALIVE_S)
            if changed:
                for ev in evs:
                    yield _event_pb(ev)
            last = new_version


def serve_grpc(application) -> None:
    """Start the TrainingControl gRPC server in a daemon thread (non-blocking)."""
    def _run() -> None:
        """Thread body: build, register, start the server and block on it."""
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
        pb_grpc.add_TrainingControlServicer_to_server(
            TrainingControlServicer(application), server
        )
        server.add_insecure_port(application.config.GRPC_LISTEN)
        server.start()
        logger.info("TrainingControl gRPC server listening on %s",
                    application.config.GRPC_LISTEN)
        server.wait_for_termination()

    threading.Thread(target=_run, daemon=True, name="training-grpc").start()
