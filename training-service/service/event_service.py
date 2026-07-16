"""Training-service event bus.

Trimmed copy of the inference-service EventService (events only — there is no
high-rate stats channel here). The gateway tails ``TrainingControl.StreamEvents``
and republishes onto its unified SSE bus, so web clients keep their single
event stream.
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

    def publish(
        self,
        event_type: str,
        keys: Optional[List[str]] = None,
        source: str = "training",
        data: Optional[Dict] = None,
    ) -> Dict:
        """Publish one event and wake all stream subscribers."""
        with self._cond:
            self._version += 1
            event = {
                "version": self._version,
                "type": event_type,
                "timestamp": time.time(),
                "source": source or "training",
                "keys": keys or [],
                "data": data or {},
            }
            self._events.append(event)
            self._cond.notify_all()
            return event

    def snapshot(self) -> Tuple[int, Dict]:
        """Return an initial snapshot event for new subscribers."""
        with self._cond:
            return self._version, {
                "version": self._version,
                "type": "state_snapshot",
                "timestamp": time.time(),
                "source": "training",
                "keys": ["training", "dataset", "sam"],
                "data": {},
            }

    def wait_for_changes(
        self, last_version: int, timeout: float
    ) -> Tuple[int, List[Dict], bool]:
        """Wait for events newer than ``last_version``.

        Returns ``(version, events, changed)``; ``changed`` is ``False`` on
        timeout (caller emits a keepalive).
        """
        with self._cond:
            changed = self._cond.wait_for(
                lambda: self._version != last_version, timeout=timeout
            )
            if not changed:
                return self._version, [], False
            events = [e for e in self._events if e["version"] > last_version]
            return self._version, events, True
