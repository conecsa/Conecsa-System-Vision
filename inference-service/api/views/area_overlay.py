"""
Detection-area editing overlay.

Visual feedback while the user positions detection areas: the frame is dimmed
outside the union of the areas being edited and each editing area gets a
dashed border matching its shape. Saved areas are intentionally invisible —
they only affect inference, not the rendered stream.
"""
# noinspection PyPackageRequirements
import numpy as np  # Package is included on os build.

# noinspection PyPackageRequirements
import cv2  # Package is included on os build.


def draw_areas(img, areas):
    """Render the editing overlay (dashed border + dim outside) onto ``img``.

    ``areas`` is the per-frame snapshot of detection areas (normalized
    [0, 1] coordinates). Returns the image unchanged when nothing is being
    edited.
    """
    if not areas:
        return img

    editing = [a for a in areas if a.is_editing]
    if not editing:
        return img  # nothing to render; saved areas stay invisible

    h, w = img.shape[:2]

    # Build a mask using only editing areas. Saved areas remain visually
    # hidden and continue to affect inference without being rendered.
    mask = np.zeros((h, w), dtype=np.uint8)
    for a in editing:
        _fill_area_into_mask(mask, a, w, h)

    # Darken everything outside the union (alpha-blend with a dim layer).
    dim = (img.astype(np.float32) * 0.4).astype(np.uint8)
    inv_mask = cv2.bitwise_not(mask)
    outside = cv2.bitwise_and(dim, dim, mask=inv_mask)
    inside = cv2.bitwise_and(img, img, mask=mask)
    img = cv2.add(inside, outside)

    # Dashed border on each editing area, matching its shape.
    for a in editing:
        x1, y1, x2, y2 = _area_bbox_px(a, w, h)
        shape = getattr(a, "shape", "rectangle")
        if shape == "circle":
            _draw_dashed_ellipse(img, x1, y1, x2, y2, color=(255, 255, 255), thickness=2)
        else:
            _draw_dashed_rect(img, x1, y1, x2, y2, color=(255, 255, 255), thickness=2)

    return img


def _area_bbox_px(area, w, h):
    """Convert a normalized area to clamped pixel bbox (x1, y1, x2, y2)."""
    x1 = max(0, int(area.x * w))
    y1 = max(0, int(area.y * h))
    x2 = min(w, int((area.x + area.width) * w))
    y2 = min(h, int((area.y + area.height) * h))
    return x1, y1, x2, y2


def _fill_area_into_mask(mask, area, w, h):
    """Stamp the area shape into a binary mask (sets pixels inside to 255)."""
    x1, y1, x2, y2 = _area_bbox_px(area, w, h)
    if x2 <= x1 or y2 <= y1:
        return
    shape = getattr(area, "shape", "rectangle")
    if shape == "circle":
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        rx = max(1, (x2 - x1) // 2)
        ry = max(1, (y2 - y1) // 2)
        cv2.ellipse(mask, (cx, cy), (rx, ry), 0, 0, 360, 255, thickness=-1)
    else:
        mask[y1:y2, x1:x2] = 255


def _draw_dashed_segments(img, points, color, thickness=2, dash=12, gap=8, closed=True):
    """Draw a dashed polyline through `points` (list of (x, y) tuples)."""
    n = len(points)
    if n < 2:
        return
    last = n if closed else n - 1
    for i in range(last):
        ax, ay = points[i]
        bx, by = points[(i + 1) % n]
        length = int(((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5)
        if length == 0:
            continue
        steps = max(1, length // (dash + gap))
        for k in range(steps + 1):
            t0 = k * (dash + gap) / length
            t1 = min(1.0, t0 + dash / length)
            if t0 >= 1.0:
                break
            sx = int(ax + (bx - ax) * t0)
            sy = int(ay + (by - ay) * t0)
            ex = int(ax + (bx - ax) * t1)
            ey = int(ay + (by - ay) * t1)
            cv2.line(img, (sx, sy), (ex, ey), color, thickness, cv2.LINE_AA)


def _draw_dashed_rect(img, x1, y1, x2, y2, color, thickness=2, dash=12, gap=8):
    """Draw a dashed rectangle on `img`."""
    _draw_dashed_segments(
        img,
        [(x1, y1), (x2, y1), (x2, y2), (x1, y2)],
        color, thickness=thickness, dash=dash, gap=gap, closed=True,
    )


def _draw_dashed_ellipse(img, x1, y1, x2, y2, color, thickness=2, dash=12, gap=8):
    """Draw a dashed (axis-aligned) ellipse inscribed in the given bbox."""
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    rx = max(1, (x2 - x1) // 2)
    ry = max(1, (y2 - y1) // 2)
    # Sample the ellipse perimeter every 4 degrees → 90 points.
    # `ellipse2Poly` is typed as `Sequence` by the stub (the runtime
    # returns ndarray); iterating + casting to int avoids `.tolist()`
    # and keeps the points fully type-checked.
    pts = cv2.ellipse2Poly((cx, cy), (rx, ry), 0, 0, 360, 4)
    _draw_dashed_segments(
        img, [(int(p[0]), int(p[1])) for p in pts],
        color, thickness=thickness, dash=dash, gap=gap, closed=True,
    )
