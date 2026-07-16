"""Inference/device REST controllers (/api/v1/* and the /api/* aliases).

Every handler is a thin translation to gRPC (inference control + os hardware
agent) or POSIX SHM (the MJPEG feeds). Split per resource, mirroring app.py's
historic section headers: detection, streams (SSE), models, camera (feeds +
config), trigger/counter, system (config/health/power), gpio, network, classes,
areas and the simplified /api/* aliases. All submodules register onto the
single `api_bp` defined here; app.py registers the blueprint.
"""
from flask import Blueprint

api_bp = Blueprint("api", __name__)

# Importing the submodules registers their routes on `api_bp`.
from . import (  # noqa: E402,F401
    aliases,
    areas,
    camera,
    classes,
    detection,
    gpio,
    models,
    network,
    streams,
    system,
    trigger,
)
