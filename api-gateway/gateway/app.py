"""API gateway Flask app.

Mirrors the inference-service monolith's REST/SSE/MJPEG surface byte-for-byte,
but every handler is a thin translation to gRPC (inference control + os hardware
agent) or POSIX SHM (the two MJPEG feeds). The external contract — routes,
status codes, JSON shapes, protobuf negotiation, SSE envelopes — is unchanged so
the Leptos app and Node-RED flows need no edits.

This module only assembles the app: the handlers live in the `controllers`
package (per-resource, on `api_bp`), the training surface in `training` and
device enrollment in `enroll`; shared response/event helpers are in `helpers`.
"""
import logging

from flask import Flask

from .helpers import _json

logger = logging.getLogger(__name__)

app = Flask(__name__)
# Bound multipart uploads (models, dataset ZIPs) before they hit the relays;
# the training-service enforces its own TRAINING_MAX_UPLOAD_MB on top.
app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024

# No CORS: the frontend is served same-origin (through the device's nginx and the
# hub's reverse proxy), so cross-origin access is neither needed nor allowed.

# Inference/device surface (/api/v1/* and the /api/* aliases).
from .controllers import api_bp  # noqa: E402
app.register_blueprint(api_bp)

# Training-service surface (/api/v1/training/*) lives in its own package.
from .training import training_bp  # noqa: E402
app.register_blueprint(training_bp)

# Device enrollment surface (/enroll/*): the hub pairs the device and signs its
# server certificate. Kept outside /api so it stays reachable during bootstrap.
from .enroll import enroll_bp  # noqa: E402
app.register_blueprint(enroll_bp)


@app.errorhandler(Exception)
def handle_exception(ex):
    """Flask error handler."""
    logger.error("Unhandled exception: %s", ex)
    return _json({"error": "Internal server error", "message": str(ex),
                  "type": type(ex).__name__}, 500)


@app.errorhandler(404)
def not_found(_):
    """Flask error handler."""
    return _json({"error": "Route not found"}, 404)
