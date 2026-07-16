"""Headless training-service entry point.

Wires the services (composition root) and starts the TrainingControl gRPC
server (proto/training.proto :50071), then blocks. The api-gateway owns all
HTTP/SSE — there is no Flask here (same shape as the inference-service).
"""
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

from service.composition import Application  # noqa: E402
from service.training_grpc import serve_grpc  # noqa: E402

logger = logging.getLogger(__name__)

application = Application()
serve_grpc(application)

if __name__ == "__main__":
    logger.info("training-service running headless (gRPC only).")
    threading.Event().wait()
