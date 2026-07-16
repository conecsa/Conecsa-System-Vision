"""Unit tests for the in-process EventService bus."""
from api.services.event_service import EventService


class TestPublishAndSnapshot:
    def test_publish_increments_version(self):
        svc = EventService()
        e1 = svc.publish("models_changed", keys=["models"])
        e2 = svc.publish("classes_changed", keys=["classes"])
        assert e1["version"] == 1
        assert e2["version"] == 2
        assert e1["type"] == "models_changed"
        assert e1["keys"] == ["models"]

    def test_publish_defaults(self):
        svc = EventService()
        e = svc.publish("thing")
        assert e["source"] == "api"
        assert e["keys"] == []
        assert e["data"] == {}

    def test_snapshot_reports_current_version(self):
        svc = EventService()
        svc.publish("a")
        version, snap = svc.snapshot()
        assert version == 1
        assert snap["type"] == "state_snapshot"
        assert "models" in snap["keys"]


class TestWaitForChanges:
    def test_returns_new_events_since_version(self):
        svc = EventService()
        svc.publish("a")
        svc.publish("b")
        version, events, _sv, _stats, changed = svc.wait_for_changes(
            last_version=1, last_stats_version=None, timeout=0.1
        )
        assert changed is True
        assert version == 2
        assert [e["type"] for e in events] == ["b"]

    def test_timeout_returns_not_changed(self):
        svc = EventService()
        version, events, _sv, stats, changed = svc.wait_for_changes(
            last_version=0, last_stats_version=None, timeout=0.05
        )
        assert changed is False
        assert events == []
        assert stats is None

    def test_replay_only_returns_events_still_in_buffer(self):
        svc = EventService(history_limit=2)
        for _ in range(5):
            svc.publish("x")  # versions 1..5; buffer keeps only 4 and 5
        _version, events, _sv, _stats, changed = svc.wait_for_changes(
            last_version=0, last_stats_version=None, timeout=0.1
        )
        assert changed is True
        # Evicted events (1..3) are gone; only the retained newer ones replay.
        assert [e["version"] for e in events] == [4, 5]

    def test_subscriber_ahead_of_buffer_forces_snapshot(self):
        # If last_version is ahead of every buffered event (e.g. a version
        # counter reset), a full-reconciliation snapshot is emitted.
        svc = EventService(history_limit=2)
        svc.publish("a")
        svc.publish("b")  # version now 2; buffer holds versions 1 and 2
        _version, events, _sv, _stats, changed = svc.wait_for_changes(
            last_version=10, last_stats_version=None, timeout=0.1
        )
        assert changed is True
        assert len(events) == 1
        assert events[0]["type"] == "state_snapshot"
        assert events[0]["version"] == 2

    def test_stats_channel_wakes_waiter(self):
        svc = EventService()
        svc.publish_stats({"fps": 30})
        _version, _events, stats_version, stats, changed = svc.wait_for_changes(
            last_version=0, last_stats_version=0, timeout=0.1
        )
        assert changed is True
        assert stats == {"fps": 30}
        assert stats_version == 1

    def test_stats_opt_out_with_none(self):
        svc = EventService()
        svc.publish_stats({"fps": 30})
        # last_stats_version None => ignore stats entirely => timeout.
        _version, _events, stats_version, stats, changed = svc.wait_for_changes(
            last_version=0, last_stats_version=None, timeout=0.05
        )
        assert changed is False
        assert stats is None
        assert stats_version is None
