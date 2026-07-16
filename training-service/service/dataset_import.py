"""Import of a pre-existing YOLO-format dataset uploaded as a ZIP.

Validates the archive (structure, classes, label syntax) and normalizes it
into the internal dataset layout: every image is re-encoded as a 640×640
letterboxed JPEG — the label editor, SAM worker and trainer all assume that
geometry — and the label coordinates (normalized on the original W×H) are
transformed onto the letterboxed square with the exact same rounding as
``letterbox_square``.

Accepted layouts inside the ZIP (Roboflow / ultralytics exports):

    data.yaml + train|valid|test/images/*.jpg + .../labels/*.txt
    data.yaml + images/*.jpg + labels/*.txt
    classes.txt instead of data.yaml; sibling .txt next to each image as a
    last-resort pairing when no images/ directory exists.

Label rows may be detection ("class cx cy w h") or segmentation
("class x1 y1 x2 y2 ..."); polygons are collapsed to their bounding box.

All failures raise DatasetImportError with an operator-readable message.
"""
import json
import logging
import os
import shutil
import uuid
import zipfile
from typing import Dict, List, Optional, Tuple

import cv2
import yaml

from .capture_service import letterbox_square
from .dataset_service import DatasetError

logger = logging.getLogger(__name__)

_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
# Same character policy as class names in dataset_service.
_NAME_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.")


class DatasetImportError(DatasetError):
    """Validation failure surfaced verbatim to the user."""


def import_dataset_zip(zip_path: str, dest_dir: str, img_size: int = 640,
                       max_total_mb: int = 512) -> Tuple[List[str], int]:
    """Validate ``zip_path`` and materialize it into ``dest_dir`` (staging).

    Returns (classes, imported_image_count). The caller owns cleanup of
    ``dest_dir`` on failure and the atomic rename into place on success.
    """
    extract_dir = os.path.join(dest_dir, ".extract")
    os.makedirs(os.path.join(dest_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(dest_dir, "labels"), exist_ok=True)
    try:
        _extract(zip_path, extract_dir, max_total_mb)
        classes = _find_classes(extract_dir)
        pairs = _collect_pairs(extract_dir)
        count = _normalize(pairs, classes, dest_dir, img_size)
    finally:
        shutil.rmtree(extract_dir, ignore_errors=True)

    with open(os.path.join(dest_dir, "classes.json"), "w") as f:
        json.dump(classes, f, ensure_ascii=False)
    logger.info("Imported dataset: %d images, %d classes", count, len(classes))
    return classes, count


# ── extraction ────────────────────────────────────────────────────────────────

def _extract(zip_path: str, extract_dir: str, max_total_mb: int) -> None:
    """Extract."""
    os.makedirs(extract_dir, exist_ok=True)
    budget = max_total_mb * 1024 * 1024
    total = 0
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise DatasetImportError("The uploaded file is not a valid ZIP archive")
    with archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir() or name.startswith("__MACOSX/"):
                continue
            if os.path.basename(name).startswith("."):
                continue
            target = os.path.normpath(os.path.join(extract_dir, name))
            if not target.startswith(os.path.abspath(extract_dir) + os.sep) \
                    and target != os.path.abspath(extract_dir):
                raise DatasetImportError(f"ZIP entry escapes the archive: '{name}'")
            total += info.file_size
            if total > budget:
                raise DatasetImportError(
                    f"Uncompressed dataset exceeds the {max_total_mb} MB limit"
                )
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with archive.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ── classes ───────────────────────────────────────────────────────────────────

def _find_classes(extract_dir: str) -> List[str]:
    """Find classes."""
    yaml_path = _find_file(extract_dir, ("data.yaml", "dataset.yaml"), max_depth=2)
    if yaml_path is not None:
        return _classes_from_yaml(yaml_path)
    txt_path = _find_file(extract_dir, ("classes.txt",), max_depth=2)
    if txt_path is not None:
        with open(txt_path, "r") as f:
            names = [line.strip() for line in f if line.strip()]
        return _validate_classes(names, txt_path)
    raise DatasetImportError(
        "No data.yaml or classes.txt found — the ZIP must be a YOLO "
        "dataset export (images/ + labels/ + data.yaml)"
    )


def _find_file(root: str, names: Tuple[str, ...], max_depth: int) -> Optional[str]:
    """Find file."""
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - base_depth >= max_depth:
            dirnames[:] = []
            continue
        for name in names:
            if name in filenames:
                return os.path.join(dirpath, name)
    return None


def _classes_from_yaml(yaml_path: str) -> List[str]:
    """Classes from yaml."""
    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise DatasetImportError(f"Could not parse data.yaml: {exc}")
    names = (data or {}).get("names")
    if isinstance(names, dict):
        # id->name mapping: order by integer id when possible, else by sorted
        # key order. Keep the dict in its own variable so the except branch still
        # sees a dict (names is rebound to a list above).
        names_map = names
        try:
            names = [str(names_map[k]) for k in sorted(names_map, key=int)]
        except (ValueError, TypeError):
            names = [str(v) for _, v in sorted(names_map.items())]
    if not isinstance(names, list) or not names:
        raise DatasetImportError("data.yaml has no 'names' class list")
    return _validate_classes([str(n) for n in names], yaml_path)


def _validate_classes(names: List[str], source: str) -> List[str]:
    """Validate classes."""
    if not names:
        raise DatasetImportError(f"No class names found in {os.path.basename(source)}")
    for name in names:
        if not name or len(name) > 64 or not all(c in _NAME_SAFE for c in name):
            raise DatasetImportError(f"Invalid class name '{name}'")
    if len(set(names)) != len(names):
        raise DatasetImportError("Duplicate class names in the dataset")
    return names


# ── image/label pairing ───────────────────────────────────────────────────────

def _label_for(image_path: str) -> str:
    """YOLO pairing: swap the innermost 'images' path component for 'labels'
    (or look for a sibling .txt when there is no images/ directory)."""
    parts = image_path.split(os.sep)
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] == "images":
            parts[i] = "labels"
            break
    parts[-1] = os.path.splitext(parts[-1])[0] + ".txt"
    return os.sep.join(parts)


def _collect_pairs(extract_dir: str) -> List[Tuple[str, Optional[str]]]:
    """(image_path, label_path|None) pairs; labels resolved YOLO-style."""
    all_images: List[str] = []
    for dirpath, _dirnames, filenames in os.walk(extract_dir):
        for name in sorted(filenames):
            if name.lower().endswith(_IMAGE_EXTS):
                all_images.append(os.path.join(dirpath, name))
    in_images_dirs = [
        p for p in all_images
        if "images" in os.path.relpath(p, extract_dir).split(os.sep)[:-1]
    ]
    # YOLO layout present: ignore stray images outside images/ directories.
    images = in_images_dirs or all_images
    if not images:
        raise DatasetImportError("No images found in the ZIP")
    pairs: List[Tuple[str, Optional[str]]] = []
    for image_path in images:
        label_path = _label_for(image_path)
        pairs.append((image_path,
                      label_path if os.path.isfile(label_path) else None))
    return pairs


# ── normalization ─────────────────────────────────────────────────────────────

def _parse_label_file(path: str, n_classes: int) -> List[Tuple[int, float, float, float, float]]:
    """Parse one YOLO label file into (class, cx, cy, w, h) boxes.

    Accepts both export flavors: detection rows ("class cx cy w h") and
    segmentation rows ("class x1 y1 x2 y2 ..." polygon) — polygons are
    converted to their bounding box, since the trainer runs detection.
    """
    boxes: List[Tuple[int, float, float, float, float]] = []
    with open(path, "r") as f:
        for lineno, line in enumerate(f, 1):
            parts = line.split()
            if not parts:
                continue
            try:
                cls = int(parts[0])
                coords = [float(v) for v in parts[1:]]
            except ValueError:
                raise DatasetImportError(
                    f"Invalid label file '{os.path.basename(path)}' line {lineno}: "
                    f"not numeric"
                )
            if not 0 <= cls < n_classes:
                raise DatasetImportError(
                    f"Invalid label file '{os.path.basename(path)}' line {lineno}: "
                    f"class id {cls} out of range (dataset has {n_classes} classes)"
                )
            if not all(0.0 <= v <= 1.0 for v in coords):
                raise DatasetImportError(
                    f"Invalid label file '{os.path.basename(path)}' line {lineno}: "
                    f"coordinates must be normalized (0..1)"
                )
            if len(coords) == 4:
                boxes.append((cls, coords[0], coords[1], coords[2], coords[3]))
            elif len(coords) >= 6 and len(coords) % 2 == 0:
                xs, ys = coords[0::2], coords[1::2]
                w, h = max(xs) - min(xs), max(ys) - min(ys)
                boxes.append((cls, min(xs) + w / 2, min(ys) + h / 2, w, h))
            else:
                raise DatasetImportError(
                    f"Invalid label file '{os.path.basename(path)}' line {lineno}: "
                    f"expected 'class cx cy w h' or 'class x1 y1 x2 y2 ...' "
                    f"(polygon), got {len(parts)} values"
                )
    return boxes


def _normalize(pairs, classes: List[str], dest_dir: str, img_size: int) -> int:
    """Normalize."""
    count = 0
    for image_path, label_path in pairs:
        boxes = _parse_label_file(label_path, len(classes)) if label_path else []
        img = cv2.imread(image_path)
        if img is None:
            raise DatasetImportError(
                f"Could not decode image '{os.path.basename(image_path)}'"
            )
        h, w = img.shape[:2]
        boxed = letterbox_square(img, img_size)
        ok, buf = cv2.imencode(".jpg", boxed, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise DatasetImportError(
                f"Could not re-encode image '{os.path.basename(image_path)}'"
            )

        image_id = str(uuid.uuid4())
        with open(os.path.join(dest_dir, "images", f"{image_id}.jpg"), "wb") as f:
            f.write(buf.tobytes())

        if boxes:
            # Same rounding as letterbox_square so boxes land exactly on the
            # letterboxed pixels.
            scale = min(img_size / w, img_size / h)
            nw = max(1, int(round(w * scale)))
            nh = max(1, int(round(h * scale)))
            left = (img_size - nw) // 2
            top = (img_size - nh) // 2
            lines = []
            for cls, cx, cy, bw, bh in boxes:
                ncx = min(max((cx * nw + left) / img_size, 0.0), 1.0)
                ncy = min(max((cy * nh + top) / img_size, 0.0), 1.0)
                nbw = min(max(bw * nw / img_size, 0.0), 1.0)
                nbh = min(max(bh * nh / img_size, 0.0), 1.0)
                lines.append(f"{cls} {ncx:.6f} {ncy:.6f} {nbw:.6f} {nbh:.6f}")
            with open(os.path.join(dest_dir, "labels", f"{image_id}.txt"), "w") as f:
                f.write("\n".join(lines) + "\n")
        count += 1
    return count
