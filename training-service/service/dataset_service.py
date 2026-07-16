"""One working dataset: images, YOLO labels, classes and metadata.

On-disk layout (one instance per dataset, under the training-data volume):

    {DATA_DIR}/datasets/{dataset_id}/images/{uuid}.jpg    640×640 letterboxed JPEG
    {DATA_DIR}/datasets/{dataset_id}/labels/{uuid}.txt    YOLO rows "class cx cy w h" (absent/empty = unlabeled)
    {DATA_DIR}/datasets/{dataset_id}/classes.json         ["cap", ...]
    {DATA_DIR}/datasets/{dataset_id}/meta.json            {"name", "created_at", "cover_image_id"}

Instances are created and cached by the DatasetRegistry. ``build_split``
materializes the ultralytics train/valid layout for one training job with
symlinks (same volume) plus the data.yaml, mirroring the Roboflow export
format of the reference dataset.
"""
import json
import logging
import os
import random
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Reject path tricks and characters that break ultralytics/data.yaml parsing.
_NAME_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.")
# Class names may additionally carry the "name #rrggbb" color suffix. '#' is
# safe here because data.yaml emits names as single-quoted YAML scalars, where
# '#' does not start a comment.
_CLASS_NAME_SAFE = _NAME_SAFE | {"#"}


@dataclass
class Box:
    """One YOLO label box: class id + normalized center/size (cx, cy, w, h)."""

    class_id: int
    cx: float
    cy: float
    w: float
    h: float


@dataclass
class NamedBox:
    """One pre-label carried by class name, already in letterbox YOLO space."""

    class_name: str
    cx: float
    cy: float
    w: float
    h: float


@dataclass
class ImageEntry:
    """A dataset image's metadata: id, capture time, and label state."""

    image_id: str
    created_at: float
    labeled: bool
    box_count: int
    replica: bool = False


class DatasetError(Exception):
    """Validation error surfaced to the client as Result(success=False)."""


def validate_dataset_name(name: str) -> str:
    """Validate dataset name."""
    name = (name or "").strip()
    if not name:
        raise DatasetError("Dataset name must not be empty")
    if len(name) > 64 or not all(c in _NAME_SAFE for c in name):
        raise DatasetError("Dataset name has invalid characters")
    return name


class DatasetService:
    """CRUD for one dataset's images, YOLO labels and class list on disk.

    Scoped to a single ``dataset_id`` under ``{root_dir}``; enforces name/id
    validation and refuses mutations once the dataset is frozen.
    """

    def __init__(self, dataset_id: str, root_dir: str, config):
        self.dataset_id = dataset_id
        self._root = root_dir
        self._config = config
        self._lock = threading.RLock()
        # Set by TrainingService while a job runs; dataset mutations are
        # rejected so the symlinked split cannot change under the trainer.
        self.frozen = False
        os.makedirs(self._images_dir, exist_ok=True)
        os.makedirs(self._labels_dir, exist_ok=True)

    # ── paths ─────────────────────────────────────────────────────────────────

    @property
    def _images_dir(self) -> str:
        return os.path.join(self._root, "images")

    @property
    def _labels_dir(self) -> str:
        return os.path.join(self._root, "labels")

    @property
    def _classes_file(self) -> str:
        return os.path.join(self._root, "classes.json")

    @property
    def _meta_file(self) -> str:
        return os.path.join(self._root, "meta.json")

    def _image_path(self, image_id: str) -> str:
        """Image path."""
        self._check_id(image_id)
        return os.path.join(self._images_dir, f"{image_id}.jpg")

    def _label_path(self, image_id: str) -> str:
        """Label path."""
        self._check_id(image_id)
        return os.path.join(self._labels_dir, f"{image_id}.txt")

    @staticmethod
    def _check_id(image_id: str) -> None:
        """Check id."""
        if not image_id or not all(c in "0123456789abcdef-" for c in image_id):
            raise DatasetError(f"Invalid image id '{image_id}'")

    def _check_frozen(self) -> None:
        """Check frozen."""
        if self.frozen:
            raise DatasetError("Dataset is locked while a training job is running")

    # ── images ────────────────────────────────────────────────────────────────

    def add_image(self, jpeg: bytes) -> ImageEntry:
        """Add image."""
        with self._lock:
            self._check_frozen()
            image_id = str(uuid.uuid4())
            with open(self._image_path(image_id), "wb") as f:
                f.write(jpeg)
        return ImageEntry(image_id=image_id, created_at=time.time(),
                          labeled=False, box_count=0)

    def add_labeled_image(self, jpeg: bytes, boxes: List[NamedBox]) -> ImageEntry:
        """Add an externally captured image with pre-labels by class name.

        Class names are resolved against classes.json under the lock (missing
        names are appended), so the name→id mapping stays consistent with the
        written label file. Everything is validated before any write.
        """
        with self._lock:
            self._check_frozen()
            names = [self._validate_class_name(b.class_name) for b in boxes]
            for b in boxes:
                for v in (b.cx, b.cy, b.w, b.h):
                    if not 0.0 <= v <= 1.0:
                        raise DatasetError("Box coordinates must be normalized (0..1)")
            classes = self._load_classes()
            for name in names:
                if name not in classes:
                    classes.append(name)
            resolved = [
                Box(classes.index(name), b.cx, b.cy, b.w, b.h)
                for name, b in zip(names, boxes)
            ]
            self._save_classes(classes)
            image_id = str(uuid.uuid4())
            with open(self._image_path(image_id), "wb") as f:
                f.write(jpeg)
            self._write_boxes(image_id, resolved)
        return ImageEntry(image_id=image_id, created_at=time.time(),
                          labeled=bool(resolved), box_count=len(resolved))

    def list_images(self) -> List[ImageEntry]:
        """List images."""
        with self._lock:
            replicas = set(self._load_meta().get("replica_image_ids", []))
            entries = []
            for name in os.listdir(self._images_dir):
                if not name.endswith(".jpg"):
                    continue
                image_id = name[:-4]
                path = os.path.join(self._images_dir, name)
                boxes = self._read_boxes(image_id)
                entries.append(ImageEntry(
                    image_id=image_id,
                    created_at=os.path.getmtime(path),
                    labeled=bool(boxes),
                    box_count=len(boxes),
                    replica=image_id in replicas,
                ))
            entries.sort(key=lambda e: e.created_at, reverse=True)
            return entries

    def get_image_bytes(self, image_id: str) -> bytes:
        """Get image bytes."""
        path = self._image_path(image_id)
        if not os.path.exists(path):
            raise DatasetError(f"Image '{image_id}' not found")
        with open(path, "rb") as f:
            return f.read()

    def delete_image(self, image_id: str) -> None:
        """Delete image."""
        with self._lock:
            self._check_frozen()
            path = self._image_path(image_id)
            if not os.path.exists(path):
                raise DatasetError(f"Image '{image_id}' not found")
            os.remove(path)
            label = self._label_path(image_id)
            if os.path.exists(label):
                os.remove(label)
            self._forget_replica(image_id)

    def replicate_image(self, image_id: str, count: int) -> int:
        """Duplicate a labeled, non-replica image (with its labels) ``count``
        times. Each copy gets a fresh uuid and is flagged as a replica in
        meta.json. Returns the number of copies created."""
        with self._lock:
            self._check_frozen()
            try:
                count = max(1, min(int(count), 50))
            except (TypeError, ValueError):
                raise DatasetError("Replica count must be an integer")
            if not os.path.exists(self._image_path(image_id)):
                raise DatasetError(f"Image '{image_id}' not found")
            meta = self._load_meta()
            replicas = set(meta.get("replica_image_ids", []))
            if image_id in replicas:
                raise DatasetError("Cannot replicate a replicated image")
            boxes = self._read_boxes(image_id)
            if not boxes:
                raise DatasetError("Only labeled images can be replicated")
            jpeg = self.get_image_bytes(image_id)
            created: list[str] = []
            try:
                for _ in range(count):
                    new_id = str(uuid.uuid4())
                    with open(self._image_path(new_id), "wb") as f:
                        f.write(jpeg)
                    self._write_boxes(new_id, boxes)
                    created.append(new_id)
                    replicas.add(new_id)
            except Exception:
                # Best-effort rollback so we don't leave untracked images behind.
                for rid in created:
                    for path in (self._image_path(rid), self._label_path(rid)):
                        try:
                            os.remove(path)
                        except FileNotFoundError:
                            # Rollback is idempotent: file may already be absent
                            # if creation failed part-way or it was removed earlier.
                            pass
                raise

            meta["replica_image_ids"] = sorted(replicas)
            self._save_meta(meta)
            return len(created)

    def _forget_replica(self, image_id: str) -> None:
        """Drop *image_id* from the persisted replica set (no-op if absent)."""
        meta = self._load_meta()
        replicas = meta.get("replica_image_ids")
        if isinstance(replicas, list) and image_id in replicas:
            meta["replica_image_ids"] = [r for r in replicas if r != image_id]
            self._save_meta(meta)

    # ── labels ────────────────────────────────────────────────────────────────

    def _read_boxes(self, image_id: str) -> List[Box]:
        """Read boxes."""
        path = self._label_path(image_id)
        if not os.path.exists(path):
            return []
        boxes: List[Box] = []
        with open(path, "r") as f:
            for line in f:
                parts = line.split()
                if len(parts) != 5:
                    continue
                try:
                    boxes.append(Box(int(parts[0]), float(parts[1]), float(parts[2]),
                                     float(parts[3]), float(parts[4])))
                except ValueError:
                    continue
        return boxes

    def get_labels(self, image_id: str) -> List[Box]:
        """Get labels."""
        if not os.path.exists(self._image_path(image_id)):
            raise DatasetError(f"Image '{image_id}' not found")
        with self._lock:
            return self._read_boxes(image_id)

    def set_labels(self, image_id: str, boxes: List[Box]) -> None:
        """Set labels."""
        with self._lock:
            self._check_frozen()
            if not os.path.exists(self._image_path(image_id)):
                raise DatasetError(f"Image '{image_id}' not found")
            classes = self._load_classes()
            for b in boxes:
                if not 0 <= b.class_id < len(classes):
                    raise DatasetError(f"Unknown class id {b.class_id}")
                for v in (b.cx, b.cy, b.w, b.h):
                    if not 0.0 <= v <= 1.0:
                        raise DatasetError("Box coordinates must be normalized (0..1)")
            self._write_boxes(image_id, boxes)

    def _write_boxes(self, image_id: str, boxes: List[Box]) -> None:
        """Write boxes."""
        path = self._label_path(image_id)
        if not boxes:
            if os.path.exists(path):
                os.remove(path)
            return
        lines = [
            f"{b.class_id} {b.cx:.6f} {b.cy:.6f} {b.w:.6f} {b.h:.6f}"
            for b in boxes
        ]
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")

    # ── classes ───────────────────────────────────────────────────────────────

    def _load_classes(self) -> List[str]:
        """Load classes."""
        if not os.path.exists(self._classes_file):
            return []
        try:
            with open(self._classes_file, "r") as f:
                data = json.load(f)
            return [str(c) for c in data] if isinstance(data, list) else []
        except (ValueError, OSError):
            logger.warning("classes.json unreadable; treating as empty")
            return []

    def _save_classes(self, classes: List[str]) -> None:
        """Save classes."""
        with open(self._classes_file, "w") as f:
            json.dump(classes, f, ensure_ascii=False)

    def get_classes(self) -> List[str]:
        """Get classes."""
        with self._lock:
            return self._load_classes()

    @staticmethod
    def _validate_class_name(name: str) -> str:
        """Validate class name."""
        name = (name or "").strip()
        if not name:
            raise DatasetError("Class name must not be empty")
        if len(name) > 64 or not all(c in _CLASS_NAME_SAFE for c in name):
            raise DatasetError("Class name has invalid characters")
        return name

    def add_class(self, name: str) -> List[str]:
        """Add class."""
        with self._lock:
            self._check_frozen()
            name = self._validate_class_name(name)
            classes = self._load_classes()
            if name in classes:
                raise DatasetError(f"Class '{name}' already exists")
            classes.append(name)
            self._save_classes(classes)
            return classes

    def rename_class(self, index: int, name: str) -> List[str]:
        """Rename class."""
        with self._lock:
            self._check_frozen()
            name = self._validate_class_name(name)
            classes = self._load_classes()
            if not 0 <= index < len(classes):
                raise DatasetError(f"No class at index {index}")
            if name in classes and classes[index] != name:
                raise DatasetError(f"Class '{name}' already exists")
            classes[index] = name
            self._save_classes(classes)
            return classes

    def remove_class(self, index: int) -> List[str]:
        """Remove a class: drop its boxes from every label file and decrement
        the ids above it so the label files stay consistent with classes.json."""
        with self._lock:
            self._check_frozen()
            classes = self._load_classes()
            if not 0 <= index < len(classes):
                raise DatasetError(f"No class at index {index}")
            classes.pop(index)
            for name in os.listdir(self._labels_dir):
                if not name.endswith(".txt"):
                    continue
                image_id = name[:-4]
                boxes = self._read_boxes(image_id)
                kept = [
                    Box(b.class_id - 1 if b.class_id > index else b.class_id,
                        b.cx, b.cy, b.w, b.h)
                    for b in boxes if b.class_id != index
                ]
                self._write_boxes(image_id, kept)
            self._save_classes(classes)
            return classes

    # ── metadata (name / cover) ───────────────────────────────────────────────

    def _load_meta(self) -> Dict:
        """Load meta."""
        try:
            with open(self._meta_file, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}

    def _save_meta(self, meta: Dict) -> None:
        """Save meta."""
        with open(self._meta_file, "w") as f:
            json.dump(meta, f, ensure_ascii=False)

    def write_meta(self, name: str, created_at: Optional[float] = None) -> None:
        """Write meta."""
        with self._lock:
            meta = self._load_meta()
            meta.setdefault("cover_image_id", "")
            meta["name"] = name
            meta["created_at"] = created_at or meta.get("created_at") or time.time()
            self._save_meta(meta)

    def rename(self, name: str) -> None:
        """Rename."""
        name = validate_dataset_name(name)
        with self._lock:
            meta = self._load_meta()
            meta["name"] = name
            self._save_meta(meta)

    def set_cover(self, image_id: str) -> None:
        """Set cover."""
        with self._lock:
            self._check_frozen()
            if not os.path.exists(self._image_path(image_id)):
                raise DatasetError(f"Image '{image_id}' not found")
            meta = self._load_meta()
            meta["cover_image_id"] = image_id
            self._save_meta(meta)

    def meta(self) -> Dict:
        """Registry-card metadata with the cover resolved: the explicit cover
        if that image still exists, else the first (oldest) image, else ""."""
        with self._lock:
            meta = self._load_meta()
            entries = self.list_images()
            cover = str(meta.get("cover_image_id") or "")
            if not cover or not os.path.exists(os.path.join(self._images_dir, f"{cover}.jpg")):
                # list_images() returns newest-first; default cover is the oldest image.
                cover = entries[-1].image_id if entries else ""
            return {
                "dataset_id": self.dataset_id,
                "name": str(meta.get("name") or "Unnamed"),
                "created_at": float(meta.get("created_at") or 0.0),
                "cover_image_id": cover,
                "image_count": len(entries),
                "labeled_count": sum(1 for e in entries if e.labeled),
                "class_count": len(self.get_classes()),
            }

    # ── dataset info / training gate ──────────────────────────────────────────

    def info(self) -> Dict:
        """Info."""
        with self._lock:
            entries = self.list_images()
            meta = self.meta()
            return {
                "image_count": len(entries),
                "labeled_count": sum(1 for e in entries if e.labeled),
                "classes": self.get_classes(),
                "min_images": self._config.MIN_IMAGES,
                "dataset_id": self.dataset_id,
                "name": meta["name"],
                "cover_image_id": meta["cover_image_id"],
            }

    def validate_for_training(self) -> None:
        """Validate for training."""
        info = self.info()
        if info["image_count"] < info["min_images"]:
            raise DatasetError(
                f"At least {info['min_images']} images are required "
                f"(have {info['image_count']})"
            )
        if not info["classes"]:
            raise DatasetError("Create at least one class before training")
        if info["labeled_count"] == 0:
            raise DatasetError("Label at least one image before training")

    # ── export ────────────────────────────────────────────────────────────────

    def export_zip(self, dest_path: str, num_shards: int = 0,
                   shard_index: int = 0, seed: str = "") -> int:
        """Write the dataset as a YOLO-format ZIP (the layout import accepts):
        images/{id}.jpg + labels/{id}.txt + data.yaml. Returns the image
        count. Holds the lock so the archive is a consistent snapshot.

        With ``num_shards`` > 0, exports one deterministic IID shard instead:
        images are shuffled with ``seed`` and assigned round-robin, so the N
        shards of one seed are disjoint, cover the full dataset and differ in
        size by at most one image. data.yaml always carries the full class
        list, so per-shard checkpoints stay averageable (federated training).
        """
        with self._lock:
            entries = self.list_images()
            classes = self._load_classes()
            if num_shards > 0:
                rng = random.Random(seed)
                shuffled = sorted(entries, key=lambda e: e.image_id)
                rng.shuffle(shuffled)
                entries = shuffled[shard_index::num_shards]
            with zipfile.ZipFile(dest_path, "w") as zf:
                for e in entries:
                    # JPEGs are already compressed — store, don't deflate.
                    zf.write(self._image_path(e.image_id),
                             f"images/{e.image_id}.jpg",
                             compress_type=zipfile.ZIP_STORED)
                    label = self._label_path(e.image_id)
                    if os.path.exists(label):
                        zf.write(label, f"labels/{e.image_id}.txt",
                                 compress_type=zipfile.ZIP_DEFLATED)
                names = ", ".join(f"'{c}'" for c in classes)
                zf.writestr(
                    "data.yaml",
                    f"train: images\nval: images\n\nnc: {len(classes)}\nnames: [{names}]\n",
                    compress_type=zipfile.ZIP_DEFLATED,
                )
            return len(entries)

    # ── split builder ─────────────────────────────────────────────────────────

    def build_split(self, job_id: str, val_fraction: float = 0.2) -> str:
        """Create the train/valid symlink layout + data.yaml for one job.

        Returns the data.yaml path. Only labeled images participate —
        ultralytics treats label-less images as background, which is rarely
        what an operator collecting 20 captures intends.
        """
        with self._lock:
            entries = [e for e in self.list_images() if e.labeled]
            if not entries:
                raise DatasetError("No labeled images to train on")
            classes = self._load_classes()

            root = os.path.join(self._config.runs_dir, job_id, "dataset")
            for split in ("train", "valid"):
                os.makedirs(os.path.join(root, split, "images"), exist_ok=True)
                os.makedirs(os.path.join(root, split, "labels"), exist_ok=True)

            rng = random.Random(job_id)
            shuffled = entries[:]
            rng.shuffle(shuffled)
            # At least 1 validation image, at least 1 training image.
            n_val = min(max(1, int(round(len(shuffled) * val_fraction))),
                        len(shuffled) - 1)
            splits = {"valid": shuffled[:n_val], "train": shuffled[n_val:]}

            for split, items in splits.items():
                for e in items:
                    os.symlink(
                        self._image_path(e.image_id),
                        os.path.join(root, split, "images", f"{e.image_id}.jpg"),
                    )
                    os.symlink(
                        self._label_path(e.image_id),
                        os.path.join(root, split, "labels", f"{e.image_id}.txt"),
                    )

            yaml_path = os.path.join(root, "data.yaml")
            names = ", ".join(f"'{c}'" for c in classes)
            with open(yaml_path, "w") as f:
                f.write(
                    f"train: {os.path.join(root, 'train', 'images')}\n"
                    f"val: {os.path.join(root, 'valid', 'images')}\n"
                    f"\n"
                    f"nc: {len(classes)}\n"
                    f"names: [{names}]\n"
                )
            logger.info(
                "Built split for job %s: %d train / %d valid, %d classes",
                job_id, len(splits["train"]), len(splits["valid"]), len(classes),
            )
            return yaml_path


def validate_model_name(name: str) -> str:
    """Mandatory, filesystem-safe model name (becomes {name}.pt → {name}.engine)."""
    name = (name or "").strip()
    if not name:
        raise DatasetError("Model name is required")
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    if len(name) > 64 or not all(c in safe for c in name):
        raise DatasetError(
            "Model name may only contain letters, digits, '_' and '-' (max 64)"
        )
    return name
