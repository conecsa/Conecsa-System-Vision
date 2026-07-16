"""API gateway entry point.

The container runs ``waitress main:app`` (see Dockerfile.api-gateway), so startup
work must happen at import time — an ``if __name__`` block would never run under
the waitress CLI. We start the telemetry relays (inference StreamEvents /
StreamStats → the unified SSE bus) here, before serving.
"""
import logging
import os

from gateway.app import app  # noqa: F401 - re-exported for `waitress main:app`
from gateway.discovery import start_advertising, stop_advertising
from gateway.events import start_relays

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logging.getLogger("waitress").setLevel(logging.WARNING)
logging.getLogger("waitress.queue").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

# Subscribe to the inference telemetry streams and re-publish onto the gateway's
# unified SSE bus. Daemon threads; reconnect on their own if inference restarts.
try:
    start_relays()
except Exception as ex:  # noqa: BLE001 - never let the relay block serving
    logger.error("Failed to start telemetry relays (continuing): %s", ex)

# Advertise this device over mDNS so conecsa-hub-vision can discover it passively.
try:
    import atexit

    start_advertising()
    atexit.register(stop_advertising)
except Exception as ex:  # noqa: BLE001 - never let discovery block serving
    logger.error("Failed to start mDNS advertising (continuing): %s", ex)

# Auto-exit training mode when the driving client (the hub's federated
# coordinator) vanishes mid-run — otherwise inference would stay stopped forever.
try:
    from gateway.training.orphan import tracker

    tracker.start()
except Exception as ex:  # noqa: BLE001 - never let the watchdog block serving
    logger.error("Failed to start the orphan watchdog (continuing): %s", ex)


if __name__ == "__main__":
    # Local convenience path; the container uses the waitress CLI in the
    # Dockerfile. waitress is thread-per-connection — long-lived MJPEG/SSE
    # streams each pin a thread, so size the pool above the worst-case stream
    # count (WAITRESS_THREADS) and cap channel_timeout so dropped tabs free fast.
    from waitress import serve
    from gateway.config import settings
    threads = int(os.environ.get("WAITRESS_THREADS", str(settings.WAITRESS_THREADS)))
    serve(app, host="0.0.0.0", port=settings.PORT, threads=threads, channel_timeout=30)
