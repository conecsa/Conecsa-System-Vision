"""
Detection area service.

Owns the list of rectangular "areas of interest" used to spatially filter
inference results. Coordinates are normalized in [0, 1] so they survive
camera resolution changes.

State is persisted to a JSON file in the shared models volume so that areas
survive container restarts.
"""
import errno
import json
import logging
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_SIZE = 0.05  # smallest allowed width/height (5% of frame)
MOVE_DELTA = float(os.environ.get("AREA_MOVE_DELTA", "0.02"))
RESIZE_DELTA = float(os.environ.get("AREA_RESIZE_DELTA", "0.02"))

VALID_ACTIONS = {
    "move_up", "move_down", "move_left", "move_right",
    "grow", "shrink",
    "grow_horizontal", "shrink_horizontal",
    "grow_vertical", "shrink_vertical",
}

VALID_SHAPES = {"rectangle", "circle"}


@dataclass
class DetectionArea:
    """One area of interest — a rectangle or circle in normalized [0,1] coords."""

    id: str
    x: float
    y: float
    width: float
    height: float
    is_editing: bool
    shape: str = "rectangle"
    # Positional label ("#1", "#2", …) matching the UI chips in
    # system-vision/src/components/area_chips.rs (idx + 1). Derived from the area's
    # index in the list, kept in sync on every mutation; not persisted.
    label: str = ""

    def to_dict(self) -> dict:
        """Serialize the area to a plain dict (for JSON/state responses)."""
        return asdict(self)


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp *value* to the inclusive ``[lo, hi]`` range."""
    return max(lo, min(hi, value))


class DetectionAreaService:
    """Thread-safe repository of detection areas with JSON persistence."""

    def __init__(self, storage_path: str) -> None:
        self._storage_path = os.path.abspath(storage_path)
        self._lock = Lock()
        self._areas: List[DetectionArea] = []
        # Pre-edit snapshots keyed by area id. Captured when an existing
        # saved area enters edit mode; cleared on save/discard/delete. Not
        # persisted — a service restart implicitly commits whatever is on
        # disk (matching the existing "save on restart" behavior).
        self._pre_edit_snapshots: Dict[str, DetectionArea] = {}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def switch_storage(self, storage_path: str) -> None:
        """Point the service at a different model's areas file and reload.

        Called by ModelService on model selection so detection areas are
        scoped per-model. A model with no areas file yet starts empty.
        """
        with self._lock:
            self._storage_path = os.path.abspath(storage_path)
            self._areas = []
            self._pre_edit_snapshots = {}
        self._load()
        logger.info("Detection areas storage switched to %s", self._storage_path)

    def _load(self) -> None:
        """Load areas from the JSON storage file (empty if it doesn't exist)."""
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path, "r") as f:
                raw = json.load(f)
            self._areas = [
                DetectionArea(
                    id=str(item.get("id")),
                    x=float(item["x"]),
                    y=float(item["y"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                    # Persisted areas are never in editing mode
                    is_editing=False,
                    shape=str(item.get("shape", "rectangle")),
                )
                for item in raw.get("areas", [])
            ]
            self._relabel()
            logger.info("Loaded %d detection areas from %s", len(self._areas), self._storage_path)
        except Exception as exc:
            logger.error("Failed to load detection areas from %s: %s", self._storage_path, exc)

    def _persist(self) -> None:
        """Atomically write the current areas to the JSON storage file."""
        tmp_path = None
        try:
            storage_dir = os.path.dirname(self._storage_path)
            os.makedirs(storage_dir, exist_ok=True)
            # Don't persist the is_editing flag — it's transient UI state.
            # Persist editing areas too so they survive a restart; they'll
            # come back as saved, which matches the "save on commit" model.
            serializable = [
                {
                    "id": a.id,
                    "x": a.x,
                    "y": a.y,
                    "width": a.width,
                    "height": a.height,
                    "shape": a.shape,
                }
                for a in self._areas
            ]
            with tempfile.NamedTemporaryFile(
                "w",
                dir=storage_dir,
                prefix=".detection_areas_",
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            ) as f:
                json.dump({"areas": serializable}, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                tmp_path = f.name
            os.replace(tmp_path, self._storage_path)
        except Exception as exc:
            logger.error("Failed to persist detection areas: %s", exc)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError as cleanup_exc:
                    if cleanup_exc.errno != errno.ENOENT:
                        logger.warning(
                            "Failed to remove temporary detection area file %s: %s",
                            tmp_path,
                            cleanup_exc,
                        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list(self) -> List[DetectionArea]:
        """Return a snapshot of the current areas (safe to iterate)."""
        with self._lock:
            return list(self._areas)

    def add(self) -> DetectionArea:
        """Create a new area centered in the frame and put it in editing mode.

        Any other area currently in editing mode is committed (is_editing=False).
        """
        with self._lock:
            # Demote any existing editing area (commit its current state)
            for a in self._areas:
                if a.is_editing:
                    a.is_editing = False
                    self._pre_edit_snapshots.pop(a.id, None)

            area = DetectionArea(
                id=uuid.uuid4().hex,
                x=0.3,
                y=0.3,
                width=0.4,
                height=0.4,
                is_editing=True,
                shape="rectangle",
            )
            self._areas.append(area)
            self._relabel()
            self._persist()
            return area

    def delete(self, area_id: str) -> bool:
        """Remove an area by id; returns True if one was removed."""
        with self._lock:
            before = len(self._areas)
            self._areas = [a for a in self._areas if a.id != area_id]
            removed = len(self._areas) != before
            if removed:
                self._pre_edit_snapshots.pop(area_id, None)
                self._relabel()
                self._persist()
            return removed

    def save(self, area_id: str) -> Optional[DetectionArea]:
        """Transition an editing area into saved state."""
        with self._lock:
            area = self._find(area_id)
            if area is None:
                return None
            area.is_editing = False
            self._pre_edit_snapshots.pop(area_id, None)
            self._persist()
            return area

    def edit(self, area_id: str) -> Optional[DetectionArea]:
        """Promote a saved area back into editing mode (demotes any other)."""
        with self._lock:
            area = self._find(area_id)
            if area is None:
                return None
            # Demote others (commit their state) and snapshot this one so a
            # later discard can roll back its geometry/shape.
            for a in self._areas:
                if a.is_editing and a.id != area_id:
                    self._pre_edit_snapshots.pop(a.id, None)
                a.is_editing = (a.id == area_id)
            self._pre_edit_snapshots[area_id] = DetectionArea(
                id=area.id,
                x=area.x,
                y=area.y,
                width=area.width,
                height=area.height,
                is_editing=False,
                shape=area.shape,
            )
            self._persist()
            return area

    def discard(self, area_id: str) -> bool:
        """Discard pending edits on an area.

        - If a pre-edit snapshot exists, restore geometry/shape from it and
          exit edit mode.
        - If no snapshot exists and the area is in edit mode, it was newly
          added in this session — remove it entirely.
        - Otherwise no-op.

        Returns True if the area existed, False if not found.
        """
        with self._lock:
            area = self._find(area_id)
            if area is None:
                return False
            snapshot = self._pre_edit_snapshots.pop(area_id, None)
            if snapshot is not None:
                area.x = snapshot.x
                area.y = snapshot.y
                area.width = snapshot.width
                area.height = snapshot.height
                area.shape = snapshot.shape
                area.is_editing = False
            elif area.is_editing:
                self._areas = [a for a in self._areas if a.id != area_id]
                self._relabel()
            self._persist()
            return True

    def set_shape(self, area_id: str, shape: str) -> Optional[DetectionArea]:
        """Change the rendered/filter shape of an area."""
        if shape not in VALID_SHAPES:
            return None
        with self._lock:
            area = self._find(area_id)
            if area is None:
                return None
            area.shape = shape
            self._persist()
            return area

    def apply_command(self, area_id: str, action: str) -> Optional[DetectionArea]:
        """Apply a move/resize *action* to an area; returns it, or None if invalid."""
        if action not in VALID_ACTIONS:
            return None
        with self._lock:
            area = self._find(area_id)
            if area is None:
                return None

            if action == "move_up":
                area.y = _clamp(area.y - MOVE_DELTA, 0.0, 1.0 - area.height)
            elif action == "move_down":
                area.y = _clamp(area.y + MOVE_DELTA, 0.0, 1.0 - area.height)
            elif action == "move_left":
                area.x = _clamp(area.x - MOVE_DELTA, 0.0, 1.0 - area.width)
            elif action == "move_right":
                area.x = _clamp(area.x + MOVE_DELTA, 0.0, 1.0 - area.width)
            elif action == "grow":
                area.width = _clamp(area.width + RESIZE_DELTA, MIN_SIZE, 1.0 - area.x)
                area.height = _clamp(area.height + RESIZE_DELTA, MIN_SIZE, 1.0 - area.y)
            elif action == "shrink":
                area.width = _clamp(area.width - RESIZE_DELTA, MIN_SIZE, 1.0 - area.x)
                area.height = _clamp(area.height - RESIZE_DELTA, MIN_SIZE, 1.0 - area.y)
            elif action == "grow_horizontal":
                area.width = _clamp(area.width + RESIZE_DELTA, MIN_SIZE, 1.0 - area.x)
            elif action == "shrink_horizontal":
                area.width = _clamp(area.width - RESIZE_DELTA, MIN_SIZE, 1.0 - area.x)
            elif action == "grow_vertical":
                area.height = _clamp(area.height + RESIZE_DELTA, MIN_SIZE, 1.0 - area.y)
            elif action == "shrink_vertical":
                area.height = _clamp(area.height - RESIZE_DELTA, MIN_SIZE, 1.0 - area.y)

            self._persist()
            return area

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find(self, area_id: str) -> Optional[DetectionArea]:
        """Return the area with *area_id*, or ``None`` (caller holds the lock)."""
        for a in self._areas:
            if a.id == area_id:
                return a
        return None

    def _relabel(self) -> None:
        """Assign positional labels ("#1", "#2", …) by list index.

        Mirrors system-vision/src/components/area_chips.rs, which renders ``#{idx + 1}``.
        Called after any operation that changes membership/ordering. Must be
        invoked under ``self._lock``.
        """
        for idx, area in enumerate(self._areas):
            area.label = f"#{idx + 1}"
