"""Training-service REST surface (/api/v1/training/*).

Thin Flask blueprint relaying to the training-service's TrainingControl gRPC
(:50071), plus the GPU-handover calls to the inference-service
(ManagementControl.ReleaseRuntime/ResumeRuntime) and the CPU-only combined
camera preview. Registered by app.py; kept as a sibling package (hardware.py
precedent) so app.py stays a flat route list.

Routes are split per resource: `session` (GPU handover + preview), `datasets`
(registry + classes), `images` (capture + labels), `sam`, `weights`
(hub-orchestrated FedAvg) and `jobs` (the training run itself). Shared
JSON/gRPC helpers live in `helpers`. All submodules register onto the single
`training_bp` defined here.
"""
from flask import Blueprint

training_bp = Blueprint("training", __name__)

# Re-exported for the unit tests (historic `gateway.training` import surface).
from .helpers import _job_dict, _meta_dict, _parse_named_boxes  # noqa: E402,F401

# Importing the submodules registers their routes on `training_bp`.
from . import datasets, images, jobs, sam, session, weights  # noqa: E402,F401

# Every training-surface request counts as client activity for the orphaned-
# training watchdog (the hub polls status every 2s while it is alive).
from .orphan import tracker  # noqa: E402

training_bp.before_request(tracker.touch)
