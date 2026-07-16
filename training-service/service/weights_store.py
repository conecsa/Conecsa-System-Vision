"""Stash of opaque .pt checkpoints under {DATA_DIR}/weights/{weights_id}.pt.

Backs the federated-training RPCs: the hub uploads round weights here
(UploadWeights), training jobs stash their resulting last.pt, the averager
reads/writes checkpoints, and DownloadWeights streams them back out. Blobs
are round-scoped and disposable — the hub deletes them best-effort and
`prune()` drops anything older than WEIGHTS_TTL_SEC as the backstop.
"""
import logging
import os
import shutil
import time
import uuid
from typing import Iterable, Tuple

from .config import Config
from .dataset_service import DatasetError

logger = logging.getLogger(__name__)


class WeightsStore:
    """Flat file store of stashed checkpoints, keyed by uuid4-hex ids.

    All mutations are temp-write + atomic rename on the same volume, so a
    failed upload never leaves a partial blob behind and no locking is needed.
    """

    def __init__(self, config: Config) -> None:
        self._config = config
        os.makedirs(config.weights_dir, exist_ok=True)
        self._link_base_weights()
        self.prune()

    def _link_base_weights(self) -> None:
        """Symlink the baked-in base weights into the store.

        The trainer chdirs next to its --weights file so ultralytics' AMP
        check resolves the base model offline (see _yolo_trainer). Jobs
        started from a stashed checkpoint chdir *here*, so the base weights
        must be reachable in this directory too.
        """
        base = self._config.BASE_WEIGHTS
        link = os.path.join(self._config.weights_dir, os.path.basename(base))
        if os.path.isfile(base) and not os.path.exists(link):
            try:
                os.symlink(base, link)
            except OSError as exc:
                logger.warning("Could not link base weights into store: %s", exc)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _check_id(weights_id: str) -> None:
        """Check id."""
        if len(weights_id) != 32 or not all(c in "0123456789abcdef" for c in weights_id):
            raise DatasetError(f"Invalid weights id '{weights_id}'")

    def _blob_path(self, weights_id: str) -> str:
        """Blob path."""
        self._check_id(weights_id)
        return os.path.join(self._config.weights_dir, f"{weights_id}.pt")

    # ── public API ────────────────────────────────────────────────────────────

    def save_stream(self, chunks: Iterable[bytes]) -> Tuple[str, int]:
        """Spool an uploaded checkpoint into the store; return (id, size)."""
        self.prune()
        weights_id = uuid.uuid4().hex
        budget = self._config.MAX_WEIGHTS_UPLOAD_MB * 1024 * 1024
        tmp = os.path.join(self._config.weights_dir, f".upload-{weights_id}")
        size = 0
        try:
            with open(tmp, "wb") as f:
                for chunk in chunks:
                    size += len(chunk)
                    if size > budget:
                        raise DatasetError(
                            f"Weights exceed the "
                            f"{self._config.MAX_WEIGHTS_UPLOAD_MB}MB limit"
                        )
                    f.write(chunk)
            if size == 0:
                raise DatasetError("Weights upload is empty")
            os.rename(tmp, self._blob_path(weights_id))
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        logger.info("Stashed weights %s (%d bytes)", weights_id, size)
        return weights_id, size

    def stash_file(self, src_path: str) -> str:
        """Copy an existing checkpoint (e.g. a finished last.pt) into the store."""
        if not os.path.isfile(src_path):
            raise DatasetError(f"Checkpoint not found: {src_path}")
        weights_id = uuid.uuid4().hex
        tmp = os.path.join(self._config.weights_dir, f".stash-{weights_id}")
        try:
            shutil.copyfile(src_path, tmp)
            os.rename(tmp, self._blob_path(weights_id))
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        return weights_id

    def path(self, weights_id: str) -> str:
        """Resolve an id to its file path; raises when unknown."""
        blob = self._blob_path(weights_id)
        if not os.path.isfile(blob):
            raise DatasetError(f"Weights '{weights_id}' not found")
        return blob

    def delete(self, weights_id: str) -> None:
        """Delete a stashed checkpoint (missing ids are a no-op)."""
        self._check_id(weights_id)
        try:
            os.remove(self._blob_path(weights_id))
        except FileNotFoundError:
            # Intentionally ignore: delete is defined as a no-op for missing ids.
            logger.debug("Weights file already absent for id %s", weights_id)

    @staticmethod
    def _is_store_entry(entry: str) -> bool:
        """Only the store's own files are prunable (never the base-weights link)."""
        if entry.startswith((".upload-", ".stash-")):
            return True
        stem, ext = os.path.splitext(entry)
        return ext == ".pt" and len(stem) == 32 and \
            all(c in "0123456789abcdef" for c in stem)

    def prune(self) -> None:
        """Drop blobs (and stray temp files) older than the TTL."""
        cutoff = time.time() - self._config.WEIGHTS_TTL_SEC
        try:
            entries = os.listdir(self._config.weights_dir)
        except FileNotFoundError:
            return
        for entry in entries:
            if not self._is_store_entry(entry):
                continue
            path = os.path.join(self._config.weights_dir, entry)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    logger.info("Pruned stale weights file %s", entry)
            except OSError:
                continue
