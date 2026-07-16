"""Unit tests for the gateway EventService bus."""
from gateway.events import EventService


class TestPublishSnapshot:
    def test_publish_increments_version(self):
        svc = EventService()
        assert svc.publish("a")["version"] == 1
        assert svc.publish("b")["version"] == 2

    def test_snapshot_keys(self):
        svc = EventService()
        _v, snap = svc.snapshot()
        assert snap["type"] == "state_snapshot"
        assert "models" in snap["keys"]

    def test_stats_snapshot(self):
        svc = EventService()
        svc.publish_stats({"fps": 12})
        version, stats = svc.stats_snapshot()
        assert version == 1
        assert stats == {"fps": 12}


class TestWaitForChanges:
    def test_new_events_since_version(self):
        svc = EventService()
        svc.publish("a")
        svc.publish("b")
        version, events, _sv, _stats, changed = svc.wait_for_changes(1, None, 0.1)
        assert changed is True
        assert version == 2
        assert [e["type"] for e in events] == ["b"]

    def test_timeout(self):
        svc = EventService()
        _v, events, _sv, stats, changed = svc.wait_for_changes(0, None, 0.05)
        assert changed is False
        assert events == []
        assert stats is None

    def test_stats_channel_wakes_waiter(self):
        svc = EventService()
        svc.publish_stats({"fps": 30})
        _v, _events, stats_version, stats, changed = svc.wait_for_changes(0, 0, 0.1)
        assert changed is True
        assert stats == {"fps": 30}
        assert stats_version == 1

    def test_stats_opt_out(self):
        svc = EventService()
        svc.publish_stats({"fps": 30})
        _v, _events, stats_version, stats, changed = svc.wait_for_changes(0, None, 0.05)
        assert changed is False
        assert stats_version is None
