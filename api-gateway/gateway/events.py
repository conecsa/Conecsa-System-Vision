"""Unified event bus + telemetry relay for the gateway's SSE stream.

``EventService`` is the same thread-safe in-process bus the monolith used (one
SSE connection per client, invalidation events + a multiplexed latest-value stats
channel). The gateway owns it now. Two background relays feed it from the
headless inference-service:

  - ``StreamEvents`` → re-published as invalidation events (conversion progress,
    model-changed, and any other pipeline-originated events).
  - ``StreamStats``  → pushed onto the latest-value stats channel.

User-initiated invalidations (start/stop/threshold/…) are published directly by
the route handlers, exactly as the monolith's routes did.
"""
import json
import logging
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class EventService:
    """Thread-safe in-process event bus with a small replay buffer."""

    def __init__(self, history_limit: int = 200):
        self._cond = threading.Condition()
        self._version = 0
        self._history_limit = history_limit
        self._events: Deque[Dict] = deque(maxlen=history_limit)
        self._stats_version = 0
        self._stats: Dict = {}

    def publish(
        self,
        event_type: str,
        keys: Optional[List[str]] = None,
        source: str = "api",
        data: Optional[Dict] = None,
    ) -> Dict:
        """Append an invalidation event, bump the version, and wake waiters."""
        with self._cond:
            self._version += 1
            event = {
                "version": self._version,
                "type": event_type,
                "timestamp": time.time(),
                "source": source or "api",
                "keys": keys or [],
                "data": data or {},
            }
            self._events.append(event)
            self._cond.notify_all()
            return event

    def publish_stats(self, stats: Dict) -> None:
        """Replace the latest stats snapshot, bump its version, and wake waiters."""
        with self._cond:
            self._stats_version += 1
            self._stats = stats or {}
            self._cond.notify_all()

    def snapshot(self) -> Tuple[int, Dict]:
        """Return ``(version, state_snapshot)`` for a new SSE subscriber."""
        with self._cond:
            return self._version, self._snapshot_locked()

    def stats_snapshot(self) -> Tuple[int, Dict]:
        """Return ``(stats_version, stats)`` for a new stats subscriber."""
        with self._cond:
            return self._stats_version, dict(self._stats)

    def wait_for_changes(
        self, last_version: int, last_stats_version: Optional[int], timeout: float
    ) -> Tuple[int, List[Dict], Optional[int], Optional[Dict], bool]:
        """Block until events or stats change (or *timeout*).

        Returns ``(version, new_events, stats_version, stats, changed)``. Stats
        are only tracked when *last_stats_version* is not ``None``.
        """
        track_stats = last_stats_version is not None
        with self._cond:
            changed = self._cond.wait_for(
                lambda: self._version != last_version
                or (track_stats and self._stats_version != last_stats_version),
                timeout=timeout,
            )
            stats_version = self._stats_version if track_stats else None
            if not changed:
                return self._version, [], stats_version, None, False

            events: List[Dict] = []
            if self._version != last_version:
                events = [e for e in self._events if e["version"] > last_version]
                if not events:
                    snapshot = self._snapshot_locked()
                    snapshot["version"] = self._version
                    events = [snapshot]

            stats = (
                dict(self._stats)
                if track_stats and self._stats_version != last_stats_version
                else None
            )
            return self._version, events, stats_version, stats, True

    def _snapshot_locked(self) -> Dict:
        """Build the full state-snapshot event (caller holds ``self._cond``)."""
        return {
            "version": self._version,
            "type": "state_snapshot",
            "timestamp": time.time(),
            "source": "api",
            "keys": [
                "status",
                "models",
                "classes",
                "thresholds",
                "camera",
                "network",
                "gpio",
                "trigger",
                "areas",
            ],
            "data": {},
        }


event_service = EventService()


# ── Telemetry relay (inference StreamEvents / StreamStats → local bus) ─────────

_RECONNECT_BACKOFF_S = 2.0


def _relay_events() -> None:
    """Re-publish inference-originated events onto the local bus."""
    from .grpc_clients import clients, inf
    last_err: Optional[str] = None
    while True:
        try:
            for ev in clients.detection.StreamEvents(inf.Empty()):
                last_err = None  # connected: a future disconnect logs again
                try:
                    data = json.loads(ev.data) if ev.data else {}
                except ValueError:
                    data = {}
                # Preserve the original type/keys/source; the local bus assigns
                # its own version (it is the source of truth for SSE clients).
                event_service.publish(
                    ev.type or "state_snapshot",
                    keys=list(ev.keys),
                    source=ev.source or "inference",
                    data=data,
                )
        except Exception as exc:  # noqa: BLE001 - keep retrying across restarts
            # Log once per downtime episode, not every backoff, to avoid spam
            # while the inference-service is restarting/unavailable.
            msg = str(exc)
            if msg != last_err:
                logger.warning("event relay disconnected (%s); retrying", exc)
                last_err = msg
            time.sleep(_RECONNECT_BACKOFF_S)


def _relay_stats() -> None:
    """Push inference per-frame stats onto the latest-value stats channel."""
    from .grpc_clients import clients, inf
    last_err: Optional[str] = None
    while True:
        try:
            for upd in clients.detection.StreamStats(inf.Empty()):
                last_err = None  # connected: a future disconnect logs again
                s = upd.stats
                event_service.publish_stats({
                    "fps": s.fps,
                    "inference_time": s.inference_time,
                    "detections": s.detections,
                    "frames_with_detections": s.frames_with_detections,
                })
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if msg != last_err:
                logger.warning("stats relay disconnected (%s); retrying", exc)
                last_err = msg
            time.sleep(_RECONNECT_BACKOFF_S)


def _relay_training_events() -> None:
    """Re-publish training-service events (job progress, dataset/SAM changes)."""
    from .grpc_clients import clients, trn
    last_err: Optional[str] = None
    while True:
        try:
            for ev in clients.training.StreamEvents(trn.Empty()):
                last_err = None  # connected: a future disconnect logs again
                try:
                    data = json.loads(ev.data) if ev.data else {}
                except ValueError:
                    data = {}
                event_service.publish(
                    ev.type or "state_snapshot",
                    keys=list(ev.keys),
                    source=ev.source or "training",
                    data=data,
                )
        except Exception as exc:  # noqa: BLE001 - keep retrying across restarts
            msg = str(exc)
            if msg != last_err:
                logger.warning("training event relay disconnected (%s); retrying", exc)
                last_err = msg
            time.sleep(_RECONNECT_BACKOFF_S)


def start_relays() -> None:
    """Start the daemon relay threads (idempotent per process)."""
    threading.Thread(target=_relay_events, daemon=True, name="event-relay").start()
    threading.Thread(target=_relay_stats, daemon=True, name="stats-relay").start()
    threading.Thread(target=_relay_training_events, daemon=True,
                     name="training-event-relay").start()
    logger.info("Telemetry relays started (StreamEvents + StreamStats + training)")
