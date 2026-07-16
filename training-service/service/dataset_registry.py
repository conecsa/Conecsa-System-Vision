"""Registry of working datasets under {DATA_DIR}/datasets/{dataset_id}/.

Owns dataset lifecycle (create/rename/delete/import) and hands out the
per-dataset DatasetService instances; everything dataset-scoped (images,
labels, classes, splits, freezing) lives on those instances. On first start
the pre-multi-dataset layout at {DATA_DIR}/dataset is migrated in place
(same-volume rename) as a dataset named "Default".
"""
import logging
import os
import shutil
import threading
import time
import uuid
from typing import Dict, List

from .config import Config
from .dataset_import import import_dataset_zip
from .dataset_service import DatasetError, DatasetService, validate_dataset_name

logger = logging.getLogger(__name__)


class DatasetRegistry:
    """Tracks the datasets on disk (list/create/rename/delete) under the data dir.

    Migrates any legacy single-dataset layout, scans for existing datasets, and
    publishes invalidation events on mutation.
    """

    def __init__(self, config: Config, event_service=None) -> None:
        self._config = config
        self._events = event_service
        self._lock = threading.Lock()
        self._datasets: Dict[str, DatasetService] = {}
        os.makedirs(config.datasets_dir, exist_ok=True)
        os.makedirs(config.runs_dir, exist_ok=True)
        self._migrate_legacy()
        self._scan()

    # ── startup ───────────────────────────────────────────────────────────────

    def _migrate_legacy(self) -> None:
        """Migrate legacy."""
        legacy = self._config.legacy_dataset_dir
        if not os.path.isdir(legacy):
            return
        dataset_id = str(uuid.uuid4())
        dst = self._dataset_root(dataset_id)
        os.rename(legacy, dst)  # same volume: atomic; legacy gone afterwards
        ds = DatasetService(dataset_id, dst, self._config)
        ds.write_meta("Default")
        logger.info("Migrated legacy dataset %s -> %s", legacy, dst)

    def _scan(self) -> None:
        """Scan."""
        for entry in os.listdir(self._config.datasets_dir):
            root = os.path.join(self._config.datasets_dir, entry)
            if not os.path.isfile(os.path.join(root, "meta.json")):
                continue  # staging dirs (.import-*) and strays
            try:
                self._check_id(entry)
            except DatasetError:
                logger.warning("Skipping dataset dir with invalid id: %s", entry)
                continue
            self._datasets[entry] = DatasetService(entry, root, self._config)
        logger.info("Dataset registry loaded %d dataset(s)", len(self._datasets))

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_id(dataset_id: str) -> None:
        """Check id."""
        if not dataset_id or not all(c in "0123456789abcdef-" for c in dataset_id):
            raise DatasetError(f"Invalid dataset id '{dataset_id}'")

    def _dataset_root(self, dataset_id: str) -> str:
        """Dataset root."""
        self._check_id(dataset_id)
        return os.path.join(self._config.datasets_dir, dataset_id)

    def _publish(self) -> None:
        """Publish."""
        if self._events is None:
            return
        try:
            self._events.publish(
                "datasets_changed", keys=["datasets"],
                data={"datasets": [d["dataset_id"] for d in self.list()]},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not publish datasets event: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def list(self) -> List[dict]:
        """List."""
        with self._lock:
            datasets = list(self._datasets.values())
        return sorted((ds.meta() for ds in datasets),
                      key=lambda m: m["created_at"])

    def get(self, dataset_id: str) -> DatasetService:
        """Get."""
        self._check_id(dataset_id)
        with self._lock:
            ds = self._datasets.get(dataset_id)
        if ds is None:
            raise DatasetError(f"Dataset '{dataset_id}' not found")
        return ds

    def create(self, name: str) -> dict:
        """Create."""
        name = validate_dataset_name(name)
        dataset_id = str(uuid.uuid4())
        root = self._dataset_root(dataset_id)
        ds = DatasetService(dataset_id, root, self._config)
        ds.write_meta(name)
        with self._lock:
            self._datasets[dataset_id] = ds
        self._publish()
        return ds.meta()

    def rename(self, dataset_id: str, name: str) -> dict:
        """Rename."""
        ds = self.get(dataset_id)
        ds.rename(name)
        self._publish()
        return ds.meta()

    def delete(self, dataset_id: str) -> None:
        """Delete."""
        ds = self.get(dataset_id)
        if ds.frozen:
            raise DatasetError("Dataset is locked while a training job is running")
        with self._lock:
            self._datasets.pop(dataset_id, None)
        shutil.rmtree(self._dataset_root(dataset_id), ignore_errors=True)
        self._publish()

    def import_zip(self, name: str, zip_path: str) -> dict:
        """Validate + normalize an uploaded YOLO-format ZIP into a new dataset.

        The dataset is staged next to its final location and only becomes
        visible (registered) after an atomic rename, so a failed import never
        leaves a half-imported dataset behind.
        """
        name = validate_dataset_name(name)
        dataset_id = str(uuid.uuid4())
        staging = os.path.join(self._config.datasets_dir, f".import-{dataset_id}")
        try:
            import_dataset_zip(
                zip_path, staging,
                img_size=self._config.IMG_SIZE,
                max_total_mb=self._config.MAX_DATASET_UPLOAD_MB,
            )
            root = self._dataset_root(dataset_id)
            os.rename(staging, root)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        ds = DatasetService(dataset_id, root, self._config)
        ds.write_meta(name, created_at=time.time())
        with self._lock:
            self._datasets[dataset_id] = ds
        self._publish()
        return ds.meta()
