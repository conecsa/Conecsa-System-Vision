"""SAHI-style tiled inference helpers (pure numpy).

A detector trained at 640 px sees a 1920×1080 frame downscaled roughly 3×, so
an object that is 20 px wide in the frame reaches the network at 7 px — below
what the smallest detection head resolves. Slicing Aided Hyper Inference
(SAHI, Akyon et al. 2022) sidesteps this without retraining: run the model on
overlapping square crops at native resolution, shift each crop's boxes back
into frame coordinates, and merge the duplicates that fall in the overlap
bands with non-maximum suppression (optionally alongside one full-frame pass
so large objects that straddle several tiles are still seen whole).

This module holds the geometry and the merge step, nothing else — no model,
no I/O — so that the dataset crops in ``training-service`` and the on-device
pipeline in ``inference-service`` share one implementation and the tile
layout trained on is byte-for-byte the layout deployed:

- :func:`auto_tile` — the resolution-agnostic default tile side: the frame's
  short side, so any 16:9 frame yields two columns whatever its pixel count.
- :func:`tile_grid` — deterministic, row-major square tiles clamped to the
  frame (the trailing tile in each axis slides back to the frame edge; frames
  are never padded, so the model never sees synthetic borders).
- :func:`tile_crop` / :func:`shift_boxes` — zero-copy crop and the inverse
  coordinate shift.
- :func:`clip_box` / :func:`tile_label_rows` — the training-side counterpart:
  ground-truth boxes clipped into a tile and rewritten as tile-normalised
  YOLO rows, so a model is trained on exactly the crops it will be run on.
- :func:`iou_matrix` / :func:`merge_tiles` — pairwise IoU and greedy NMS over
  the union of per-tile detections.

NMS is deliberately re-implemented here in numpy although both consumers
have faster kernels at hand (``cv2.dnn.NMSBoxes`` in the inference pipeline,
``torchvision.ops.nms`` in the trainer). ``conecsa_common`` is the Apache-2.0
layer shared by every service and must stay importable without cv2 or torch;
a few hundred boxes per frame is far below the point where the numpy loop
matters, and one implementation on both sides keeps the offline metrics
honest about what the device will produce.
"""
from dataclasses import dataclass

import numpy as np

__all__ = [
    "Tile",
    "auto_tile",
    "clip_box",
    "iou_matrix",
    "merge_tiles",
    "shift_boxes",
    "tile_crop",
    "tile_grid",
    "tile_label_rows",
]


@dataclass(frozen=True)
class Tile:
    """A pixel box inside a frame; ``x1``/``y1`` are exclusive."""

    x0: int
    y0: int
    x1: int
    y1: int

    def __post_init__(self) -> None:
        if self.x0 < 0 or self.y0 < 0:
            raise ValueError(f"tile origin must be non-negative, got ({self.x0}, {self.y0})")
        if self.x1 <= self.x0 or self.y1 <= self.y0:
            raise ValueError(
                f"tile must have positive size, got ({self.x0}, {self.y0}, {self.x1}, {self.y1})"
            )

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0


def auto_tile(width: int, height: int) -> int:
    """The default tile side for a ``width``×``height`` frame: its short side.

    Tiles are square, so a tile spanning the short side turns the frame into
    a single row (or column) of overlapping crops whose count depends only on
    the aspect ratio, never on the pixel count: a 1280×720, 1920×1080 or
    3840×2160 frame all give two columns (K=2), 4:3 gives two heavily
    overlapping ones, wider than 1.8:1 gives three, a square frame gives
    one. Training
    crops and inference crops computed this way stay the same geometry on
    every camera the device may be fitted with.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"frame size must be positive, got {width}x{height}")
    return min(width, height)


def _axis_starts(length: int, tile: int, stride: int) -> list[int]:
    """Tile origins along one axis: fixed stride, last one flush with the edge."""
    if length <= tile:
        return [0]
    starts: list[int] = []
    start = 0
    while start + tile < length:
        starts.append(start)
        start += stride
    # The next tile would run past the edge: slide it back so it ends exactly
    # at the frame border instead of padding. It is never a duplicate of the
    # previous start because that one satisfied start + tile < length.
    starts.append(length - tile)
    return starts


def tile_grid(
    width: int,
    height: int,
    tile: int,
    overlap: float = 0.2,
    include_full: bool = False,
) -> list[Tile]:
    """Square tiles of side ``tile`` covering a ``width``×``height`` frame.

    Adjacent tiles overlap by ``round(overlap * tile)`` pixels
    (``0 <= overlap < 1``). Tiles are clamped to the frame: the last tile in
    each axis is shifted back so it ends at the frame edge, never padded. If
    the frame is smaller than ``tile`` in an axis, a single tile spans that
    axis. Order is deterministic and row-major (left to right, then top to
    bottom). ``include_full=True`` appends ``Tile(0, 0, width, height)`` as
    the *last* element so callers can run one whole-frame pass for large
    objects.

    Raises :class:`ValueError` on non-positive sizes or an overlap outside
    ``[0, 1)``.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"frame size must be positive, got {width}x{height}")
    if tile <= 0:
        raise ValueError(f"tile side must be positive, got {tile}")
    if not 0.0 <= overlap < 1.0:
        raise ValueError(f"overlap must be in [0, 1), got {overlap}")

    # overlap < 1 keeps the stride at least 1 except for pathological
    # round-ups on tiny tiles; the max() guarantees the loop terminates.
    stride = max(1, tile - int(round(overlap * tile)))
    xs = _axis_starts(width, tile, stride)
    ys = _axis_starts(height, tile, stride)
    tile_w = min(tile, width)
    tile_h = min(tile, height)

    tiles = [Tile(x, y, x + tile_w, y + tile_h) for y in ys for x in xs]
    if include_full:
        tiles.append(Tile(0, 0, width, height))
    return tiles


def tile_crop(frame: np.ndarray, tile: Tile) -> np.ndarray:
    """The ``frame[y0:y1, x0:x1]`` view for ``tile`` (no copy)."""
    return frame[tile.y0:tile.y1, tile.x0:tile.x1]


def clip_box(box_xyxy, tile: Tile) -> tuple[list[float], float]:
    """Intersect one pixel ``xyxy`` box with ``tile``.

    Returns the clipped box in tile-relative pixels and the fraction of the
    original box area that lies inside the tile; ``([], 0.0)`` when the box
    is degenerate or disjoint from the tile.
    """
    bx0, by0, bx1, by1 = (float(v) for v in box_xyxy)
    x0, y0 = max(bx0, tile.x0), max(by0, tile.y0)
    x1, y1 = min(bx1, tile.x1), min(by1, tile.y1)
    area = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if area <= 0.0 or inter <= 0.0:
        return [], 0.0
    return [x0 - tile.x0, y0 - tile.y0, x1 - tile.x0, y1 - tile.y0], inter / area


def tile_label_rows(
    class_ids,
    boxes_xyxy,
    tile: Tile,
    min_visible: float = 0.25,
) -> tuple[list[str], int]:
    """Ground-truth boxes of one frame rewritten as YOLO rows for ``tile``.

    ``class_ids`` and ``boxes_xyxy`` (frame pixels) are parallel sequences.
    A box is kept when at least ``min_visible`` of its area lies inside the
    tile, clipped to the tile and normalised to the tile's size as
    ``"class cx cy w h"``. Returns the rows and the number of boxes that
    *touch* the tile at all, so the caller can tell a genuinely empty tile
    (a valid negative) from one whose only content was a discarded fragment
    (which would teach the model that a visible piece of an object is
    background and should be skipped).
    """
    if not 0.0 < min_visible <= 1.0:
        raise ValueError(f"min_visible must be in (0, 1], got {min_visible}")
    ids = list(class_ids)
    boxes = list(boxes_xyxy)
    if len(ids) != len(boxes):
        raise ValueError(f"class_ids and boxes_xyxy disagree on N: {len(ids)}, {len(boxes)}")
    rows: list[str] = []
    touched = 0
    for class_id, box in zip(ids, boxes, strict=True):
        clipped, visible = clip_box(box, tile)
        if visible <= 0.0:
            continue
        touched += 1
        if visible < min_visible:
            continue
        cx = (clipped[0] + clipped[2]) / 2.0 / tile.width
        cy = (clipped[1] + clipped[3]) / 2.0 / tile.height
        w = (clipped[2] - clipped[0]) / tile.width
        h = (clipped[3] - clipped[1]) / tile.height
        rows.append(f"{int(class_id)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    return rows, touched


def _as_boxes(boxes: np.ndarray, name: str) -> np.ndarray:
    """Validate an ``(N, 4)`` box array and return it as a float array."""
    arr = np.asarray(boxes)
    if arr.size == 0:
        arr = arr.reshape(0, 4)
    if arr.ndim != 2 or arr.shape[1] != 4:
        raise ValueError(f"{name} must have shape (N, 4), got {arr.shape}")
    if not np.issubdtype(arr.dtype, np.floating):
        arr = arr.astype(np.float64)
    return arr


def shift_boxes(boxes_xyxy: np.ndarray, ox: int, oy: int) -> np.ndarray:
    """Translate ``(N, 4)`` xyxy boxes from tile space into frame space.

    Adds the tile origin ``(ox, oy)`` to both corners. Returns a new float
    array of the same shape; an empty input yields an empty ``(0, 4)`` array.
    """
    boxes = _as_boxes(boxes_xyxy, "boxes_xyxy")
    offset = np.array([ox, oy, ox, oy], dtype=boxes.dtype)
    return boxes + offset


def iou_matrix(a_xyxy: np.ndarray, b_xyxy: np.ndarray) -> np.ndarray:
    """Pairwise intersection-over-union: ``(N, 4)`` × ``(M, 4)`` → ``(N, M)``.

    Degenerate (zero-area) pairs yield 0 rather than NaN.
    """
    a = _as_boxes(a_xyxy, "a_xyxy")
    b = _as_boxes(b_xyxy, "b_xyxy")

    # Broadcast (N, 1, 2) against (1, M, 2) for the intersection corners.
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(rb - lt, 0.0, None)
    inter = wh[..., 0] * wh[..., 1]

    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter

    out = np.zeros_like(inter)
    np.divide(inter, union, out=out, where=union > 0)
    return out


def merge_tiles(
    boxes_xyxy: np.ndarray,
    scores: np.ndarray,
    classes: np.ndarray,
    iou_threshold: float = 0.5,
    class_aware: bool = True,
) -> np.ndarray:
    """Greedy NMS over detections already shifted into frame space.

    Returns the indices to *keep* as an ``int64`` array sorted by descending
    score. A box is suppressed when its IoU with an already-kept, higher
    scoring box exceeds ``iou_threshold``; with ``class_aware=True`` only
    boxes of the same class id suppress each other, so two classes may share
    a location. Ties are broken by input order, which keeps the result
    deterministic. Running the merge again on the kept set is a no-op.
    """
    if not 0.0 <= iou_threshold <= 1.0:
        raise ValueError(f"iou_threshold must be in [0, 1], got {iou_threshold}")

    boxes = _as_boxes(boxes_xyxy, "boxes_xyxy")
    score_arr = np.asarray(scores, dtype=np.float64).reshape(-1)
    class_arr = np.asarray(classes).reshape(-1)
    n = boxes.shape[0]
    if score_arr.shape[0] != n or class_arr.shape[0] != n:
        raise ValueError(
            f"boxes, scores and classes disagree on N: {n}, {score_arr.shape[0]}, "
            f"{class_arr.shape[0]}"
        )
    if n == 0:
        return np.empty(0, dtype=np.int64)

    order = np.argsort(-score_arr, kind="stable")
    ious = iou_matrix(boxes, boxes)
    if class_aware:
        # Cross-class pairs never suppress: zero their IoU up front.
        same_class = class_arr[:, None] == class_arr[None, :]
        ious = np.where(same_class, ious, 0.0)

    alive = np.ones(n, dtype=bool)
    keep: list[int] = []
    for idx in order:
        if not alive[idx]:
            continue
        keep.append(int(idx))
        alive &= ~(ious[idx] > iou_threshold)
        alive[idx] = False
    return np.asarray(keep, dtype=np.int64)
