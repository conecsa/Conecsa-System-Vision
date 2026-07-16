"""
Application event service.

Publishes lightweight invalidation events over SSE so every client surface
(web UI, Node-RED, curl-driven flows) can reconcile with the backend state.
"""
import threading
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple


class EventService:
    """Thread-safe in-process event bus with a small replay buffer."""

    def __init__(self, history_limit: int = 200):
        self._cond = threading.Condition()
        self._version = 0
        self._events: Deque[Dict] = deque(maxlen=history_limit)
        # High-rate performance stats are multiplexed onto the same SSE
        # connection so each web client needs ONE stream, not two. Stats are a
        # "latest value" channel (their own version, never appended to the
        # replay deque) so the per-frame update rate cannot evict invalidation
        # events from the history buffer.
        self._stats_version = 0
        self._stats: Dict = {}

    def publish(
        self,
        event_type: str,
        keys: Optional[List[str]] = None,
        source: str = "api",
        data: Optional[Dict] = None,
    ) -> Dict:
        """Publish one invalidation event and wake all SSE subscribers."""
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
        """Update the latest-value stats channel and wake SSE subscribers.

        Called from the detection pipeline on every stats update. Shares the
        invalidation condition so a single ``wait_for_changes`` waiter wakes on
        either an invalidation event or a stats update.
        """
        with self._cond:
            self._stats_version += 1
            self._stats = stats or {}
            self._cond.notify_all()

    def snapshot(self) -> Tuple[int, Dict]:
        """Return an initial snapshot event for new subscribers."""
        with self._cond:
            return self._version, self._snapshot_locked()

    def wait_for_changes(
        self, last_version: int, last_stats_version: Optional[int], timeout: float
    ) -> Tuple[int, List[Dict], Optional[int], Optional[Dict], bool]:
        """Wait for new invalidation events or a stats update.

        Pass ``last_stats_version=None`` to opt out of the stats channel
        entirely (e.g. Node-RED subscribers that only need invalidations) — the
        waiter then ignores stats churn and never wakes on per-frame updates.

        Returns ``(version, events, stats_version, stats, changed)`` where
        ``stats`` is the latest stats dict when it advanced past
        ``last_stats_version`` (else ``None``), and ``changed`` is ``False`` on
        timeout (caller should emit a keepalive).
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
                    # The subscriber fell behind the replay buffer. Force a full
                    # reconciliation instead of silently dropping invalidations.
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
        """Build a snapshot event. Caller must hold ``self._cond``."""
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
