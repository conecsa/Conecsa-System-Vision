"""
Processing pipeline - single shared producer that turns raw camera frames into
the processed (detection-overlaid) MJPEG stream.

Why this exists
---------------
The processed stream used to be generated *per HTTP client* in
``VideoController._generate_processed_frames`` as one serial loop:
``decode → preprocess → infer → draw → encode``. On the device that serial loop
runs at ~12 fps even though the box is ~80% idle: while the GPU runs inference
(~41 ms) the CPU is idle, and while the CPU decodes/encodes (~37 ms) the GPU is
idle. The TensorRT inference already runs in a separate process (its IPC wait
releases the GIL) and OpenCV decode/encode release the GIL too, so the stages
genuinely parallelise across the idle cores.

This service runs the stages on separate threads connected by bounded blocking
hand-offs (``queue.Queue``):

    A "prepare"  decode (reduced scale) + RGB + stereo + preprocess
    B "infer"    TensorRT inference (the GPU stage)
    C "finish"   postprocess (NMS/draw) + stats + GPIO
    D "encode"   JPEG encode + publish

With ``TENSORRT_CONTEXTS = N > 1`` the decode (A) and inference (B) stages each
get N threads — N inference contexts run in parallel (measured ~1.8x GPU
scaling) and N decode threads keep them fed — while the postprocess (C) and
encode (D) stages stay single-threaded but pipelined behind them. N=1 collapses
to the original single-lane decode∥infer∥encode pipeline.

Stage A always grabs the *freshest* camera frame and drops stale ones, so the
pipeline stays realtime; the blocking hand-offs give backpressure so the whole
thing settles at the slowest stage. The published frame is mirrored into a
shared-memory ring from which the api-gateway fans out to all HTTP clients, so
N viewers cost the same as one.

The trigger/GPIO-gate/freeze/"Detection Off" logic that used to live in the
controller generator lives here now (Stage A/C), computed once and shared.
"""
import logging
import os
import queue
import threading
import time
from typing import Optional

# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

logger = logging.getLogger(__name__)


class ProcessingPipelineService:
    """Owns the decode→infer→encode pipeline and publishes the latest frame."""

    def __init__(self, consumer_service, codec_service, detection_service,
                 stats_service, gpio_service, overlay_renderer, video_service):
        self._consumer = consumer_service
        self._codec = codec_service
        self._detection = detection_service
        self._stats = stats_service
        self._gpio = gpio_service
        self._overlay = overlay_renderer
        self._video = video_service

        # Number of parallel lanes = number of inference contexts. With N>1 the
        # decode and inference stages each get N threads so neither becomes the
        # bottleneck (decode ~30 ms and inference ~30 ms are co-limiting at N=1).
        # N=1 keeps exactly the single-lane decode∥infer∥encode pipeline.
        try:
            self._n = max(1, int(os.environ.get("TENSORRT_CONTEXTS", "1")))
        except ValueError:
            self._n = 1

        # Stage hand-offs: bounded blocking queues sized to the lane count so all
        # lanes stay fed without unbounded latency build-up.
        self._q_infer: "queue.Queue" = queue.Queue(maxsize=self._n)
        self._q_finish: "queue.Queue" = queue.Queue(maxsize=self._n)
        self._q_encode: "queue.Queue" = queue.Queue(maxsize=self._n)

        # Shared frame-claim cursor so multiple decode threads each grab a
        # distinct (freshest-available) camera frame instead of duplicating work.
        self._grab_lock = threading.Lock()
        self._last_grabbed = 0

        # In-order publish across lanes (a slower lane finishing after a newer
        # frame already went out must not push the stream backwards).
        self._last_published_seq = 0
        self._publish_lock = threading.Lock()

        # The published frame goes into a shared-memory ring from which the
        # API-gateway container fans out the processed feed — the frames never
        # cross a gRPC boundary.
        self._proc_shm = None
        try:
            from conecsa_shm.processed_ring import ProcessedFrameWriter
            self._proc_shm = ProcessedFrameWriter()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Pipeline] processed-frame SHM unavailable: %s", exc)

        # Last successfully encoded frame — re-emitted while output is frozen
        # (GPIO trigger pin low, or detection trigger disabled).
        self._frozen: Optional[bytes] = None

        # Run gate: the pipeline only does work while detection is running.
        self._gate = threading.Condition(threading.Lock())

        # FPS over the last N processed frames (mirrors VideoService.calculate_fps).
        self._frame_times: list = []
        self._fps_lock = threading.Lock()

        threads = []
        for i in range(self._n):
            threads.append((self._stage_prepare, f"pipeline-prepare-{i}"))
            threads.append((self._stage_infer, f"pipeline-infer-{i}"))
        threads.append((self._stage_finish, "pipeline-finish"))
        threads.append((self._stage_encode, "pipeline-encode"))
        for target, name in threads:
            threading.Thread(target=target, daemon=True, name=name).start()
        logger.info("[Pipeline] decode∥infer∥encode pipeline started (%d lane(s))", self._n)

    # ------------------------------------------------------------------
    # Run gate
    # ------------------------------------------------------------------

    def _wait_active(self) -> None:
        """Park the prepare stage while nothing needs processing."""
        with self._gate:
            # Short timeout so we re-check is_running, which flips via
            # DetectionService.start()/stop() without touching this condition.
            while not self._detection.is_running:
                self._gate.wait(timeout=0.5)

    # ------------------------------------------------------------------
    # Publish
    # ------------------------------------------------------------------

    def _publish(self, jpg: bytes, seq: int) -> None:
        """Publish a processed frame, keeping display in camera-frame order.

        ``seq`` is the source camera-frame sequence; frames older than the last
        published one (a slower lane finishing after a newer frame already went
        out) are dropped so the stream never goes backwards.
        """
        with self._publish_lock:
            if seq <= self._last_published_seq:
                return
            self._last_published_seq = seq
        # Mirror to the shared-memory ring outside the lock (publish() is
        # self-guarding and must not stall the publish ordering).
        if self._proc_shm is not None:
            self._proc_shm.publish(jpg)

    # ------------------------------------------------------------------
    # Stage A — decode / colour / stereo / preprocess (+ gate & freeze)
    # ------------------------------------------------------------------

    def _grab_next(self):
        """Claim the freshest not-yet-claimed camera frame (shared across lanes).

        Holding the lock across the wait makes decode threads naturally alternate
        frames: each waits for the next frame, claims it, releases. Returns
        ``(seq, jpg, npy)`` or ``None`` on timeout.
        """
        with self._grab_lock:
            seq, jpg, npy = self._consumer.wait_for(self._last_grabbed, timeout=1.0)
            if seq <= self._last_grabbed:
                return None
            self._last_grabbed = seq
            return seq, jpg, npy

    def _stage_prepare(self) -> None:
        """Stage A loop: grab the latest frame, apply the trigger/freeze gates,
        decode + colour + stereo-combine it, and hand the prepared input to the
        inference stage (or emit a freeze/"Detection Off" frame)."""
        while True:
            try:
                self._wait_active()
                grabbed = self._grab_next()
                if grabbed is None:
                    continue  # timed out — re-check the run gate
                seq, jpg, npy = grabbed

                # GPIO trigger gate: pin low → freeze output (re-emit last frame).
                if not self._gpio.should_process_frame():
                    if self._frozen is not None:
                        self._publish(self._frozen, seq)
                    continue

                # Decode (reduced scale) + software RGB + stereo combine.
                frame = self._decode(jpg, npy)
                if frame is None:
                    continue
                frame = self._codec.combine_stereo(frame)

                # Detection trigger disabled → freeze (re-emit, or make one).
                if not self._detection.get_trigger_status():
                    if self._frozen is not None:
                        self._publish(self._frozen, seq)
                    else:
                        self._emit_off(frame, seq)
                    continue

                # Active detection path → hand off to the inference stage.
                if self._detection.is_running and self._detection.is_model_loaded():
                    prepared = self._detection.prepare(frame)
                    if prepared is None:
                        self._emit_off(frame, seq)
                        continue
                    input_data, meta = prepared
                    self._handoff(self._q_infer, (seq, frame, input_data, meta))
                else:
                    # Detection off → "Detection Off" overlay.
                    self._emit_off(frame, seq)
            except Exception as ex:  # noqa: BLE001 - never let the stage thread die
                logger.error("[Pipeline] prepare stage error: %s", ex)

    def _decode(self, jpg, npy) -> Optional[np.ndarray]:
        """Return a BGR frame from a raw-RGB array or a JPEG (decoded + RGB levels)."""
        if npy is not None:
            # Raw-RGB producer: colour already applied in the webcam-server.
            return npy
        if jpg is not None:
            frame = self._codec.decode_frame_scaled(jpg)
            r, g, b = self._video.rgb_levels()
            return self._codec.apply_rgb_levels(frame, r, g, b)
        return None

    # ------------------------------------------------------------------
    # Stage B — inference (one thread per context; run_inference draws a free
    # context from the model-manager pool, so the lanes run in parallel).
    # ------------------------------------------------------------------

    def _stage_infer(self) -> None:
        """Stage B loop: run inference on prepared inputs (one thread per context,
        drawing a free context from the pool) and hand results to the finish stage."""
        while True:
            item = self._take(self._q_infer)
            if item is None:
                continue
            seq, frame, input_data, meta = item
            try:
                output_data, inference_time = self._detection.infer(input_data)
            except Exception as ex:  # noqa: BLE001
                logger.error("[Pipeline] infer stage error: %s", ex)
                continue
            self._handoff(self._q_finish, (seq, frame, output_data, meta, inference_time))

    # ------------------------------------------------------------------
    # Stage C — postprocess / draw / stats / GPIO (single thread; reads the
    # shared detector state). Hands the drawn frame to the encode stage.
    # ------------------------------------------------------------------

    def _stage_finish(self) -> None:
        """Stage C loop: postprocess/draw, update stats and the GPIO count, drop
        out-of-order frames a faster lane already superseded, then hand the drawn
        frame to the encode stage."""
        while True:
            item = self._take(self._q_finish)
            if item is None:
                continue
            seq, frame, output_data, meta, inference_time = item

            # Drop frames a faster infer lane has already superseded (out-of-order
            # completion): no stats/GPIO churn, no wasted postprocess/encode.
            with self._publish_lock:
                if seq <= self._last_published_seq:
                    continue

            try:
                result = self._detection.finish(output_data, frame, meta, inference_time)
            except Exception as ex:  # noqa: BLE001
                logger.error("[Pipeline] finish stage error: %s", ex)
                result = None

            if result is not None:
                out = result.processed_image
                num = result.num_detections
                if num > 0:
                    self._detection.increment_detection_count(num)
                self._stats.update(
                    fps=self._tick_fps(),
                    inference_time=inference_time * 1000,
                    detections=num,
                    increment_frames_with_detections=(num > 0),
                )
            else:
                out = frame

            self._handoff(self._q_encode, (seq, out))

    # ------------------------------------------------------------------
    # Stage D — JPEG encode + publish (single thread; cv2 releases the GIL so
    # this overlaps the Python-bound postprocess of the next frame).
    # ------------------------------------------------------------------

    def _stage_encode(self) -> None:
        """Stage D loop: JPEG-encode the drawn frame, cache it as the frozen frame
        and publish it to the processed SHM ring."""
        while True:
            item = self._take(self._q_encode)
            if item is None:
                continue
            seq, out = item
            encoded = self._codec.encode_frame(out)
            if encoded:
                self._frozen = encoded
                self._publish(encoded, seq)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_off(self, frame: np.ndarray, seq: int) -> None:
        """Draw the 'Detection Off' overlay, encode, publish and cache as frozen."""
        off = self._overlay.draw_detection_off_overlay(frame)
        encoded = self._codec.encode_frame(off)
        if encoded:
            self._frozen = encoded
            self._publish(encoded, seq)

    @staticmethod
    def _handoff(q: "queue.Queue", item) -> None:
        """Hand an item to the next stage, blocking until it is free.

        maxsize=1 makes this a rendezvous: it throttles the upstream stage to the
        downstream rate (so stage A only decodes as fast as inference consumes —
        no wasted decodes), while still overlapping work (A decodes the next
        frame while B infers the current one). Realtime freshness is kept because
        stage A re-grabs the *latest* camera frame after each hand-off, skipping
        any frames captured while it was blocked. A long stall (>2 s) drops the
        frame rather than wedging the thread.
        """
        try:
            q.put(item, timeout=2.0)
        except queue.Full:
            logger.warning("[Pipeline] downstream stalled — dropping frame")

    @staticmethod
    def _take(q: "queue.Queue"):
        """Pop the next item from a stage queue, or ``None`` after a 1s timeout."""
        try:
            return q.get(timeout=1.0)
        except queue.Empty:
            return None

    def _tick_fps(self) -> float:
        """Record a frame timestamp and return the rolling FPS over the last ~30."""
        with self._fps_lock:
            now = time.time()
            self._frame_times.append(now)
            if len(self._frame_times) > 30:
                self._frame_times.pop(0)
            if len(self._frame_times) > 1:
                span = self._frame_times[-1] - self._frame_times[0]
                if span > 0:
                    return (len(self._frame_times) - 1) / span
            return 0.0
