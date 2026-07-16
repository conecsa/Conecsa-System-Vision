"""
Headless inference-service entry point.

Wires the services + pipeline (composition root), restores the last model and
starts the gRPC control server (proto/inference.proto :50061), then blocks. The
api-gateway owns all HTTP/SSE/MJPEG — there is no Flask here.
"""
import logging
import threading

from api.composition import Application

logger = logging.getLogger(__name__)

application = Application()

# Restore the last-selected model + its per-model settings (thresholds,
# detection areas, camera config) and auto-start detection BEFORE serving.
# Done before the gRPC server starts so it only accepts requests once the
# restore has completed, ensuring clients fetch the correct per-model values
# on their first call.
try:
    application.initialize()
except Exception as ex:  # noqa: BLE001 - never let a restore failure block serving
    logger.error("Application initialization failed (continuing to serve): %s", ex)

# Start the DetectionControl gRPC server (proto/inference.proto on :50061).
# This is the inference-service's only external control surface; the api-gateway
# consumes it over gRPC while video frames cross via shared memory.
try:
    from api.inference_grpc import serve_grpc
    serve_grpc(application)
except Exception as ex:  # noqa: BLE001 - never let the gRPC server block serving
    logger.error("Failed to start inference gRPC server (continuing): %s", ex)

if __name__ == "__main__":
    # Headless inference: the processing pipeline and the gRPC control server
    # (proto/inference.proto on :50061) are already running from the module-level
    # startup above. The api-gateway is the only HTTP surface now — there is no
    # Flask/waitress here. Block the main thread so the daemon gRPC + pipeline
    # threads keep serving (docker stop's SIGTERM interrupts the wait and exits).
    logger.info("Inference running headless (gRPC + pipeline; no Flask/HTTP).")
    threading.Event().wait()
