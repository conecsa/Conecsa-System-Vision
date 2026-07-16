"""Composition root for the training-service (mirrors the inference-service)."""
import logging

from .capture_service import CaptureService
from .config import Config
from .dataset_registry import DatasetRegistry
from .event_service import EventService
from .sam_service import SamService
from .training_service import TrainingService
from .weights_store import WeightsStore

logger = logging.getLogger(__name__)


class Application:
    """Composition root: builds and wires the training-service's services."""

    def __init__(self):
        self.config = Config()
        self.event_service = EventService()
        # Migrates the legacy single-dataset layout on first start.
        self.dataset_registry = DatasetRegistry(
            self.config, event_service=self.event_service
        )
        self.capture_service = CaptureService(self.config)
        self.sam_service = SamService(self.config, event_service=self.event_service)
        # Checkpoint stash for federated rounds (prunes stale blobs on start).
        self.weights_store = WeightsStore(self.config)
        self.training_service = TrainingService(
            self.config,
            self.dataset_registry,
            event_service=self.event_service,
            sam_service=self.sam_service,
            weights_store=self.weights_store,
        )
        logger.info(
            "training-service wired (data=%s, gateway=%s)",
            self.config.DATA_DIR, self.config.GATEWAY_ADDR,
        )
