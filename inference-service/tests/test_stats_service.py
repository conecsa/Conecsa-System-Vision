"""Unit tests for StatsService."""
from api.services.stats_service import StatsService


class TestUpdateAndGet:
    def test_defaults_are_zero(self):
        stats = StatsService().get_stats()
        assert stats.fps == 0.0
        assert stats.detections == 0
        assert stats.frames_with_detections == 0

    def test_partial_update_keeps_others(self):
        svc = StatsService()
        svc.update(fps=30.0)
        svc.update(detections=4)
        stats = svc.get_stats()
        assert stats.fps == 30.0
        assert stats.detections == 4

    def test_increment_frames_with_detections(self):
        svc = StatsService()
        svc.update(increment_frames_with_detections=True)
        svc.update(increment_frames_with_detections=True)
        assert svc.get_stats().frames_with_detections == 2

    def test_get_stats_returns_independent_copy(self):
        svc = StatsService()
        svc.update(fps=10.0)
        snap = svc.get_stats()
        svc.update(fps=99.0)
        assert snap.fps == 10.0  # snapshot not mutated by later update


class TestReset:
    def test_reset_zeros_everything(self):
        svc = StatsService()
        svc.update(fps=30.0, detections=5, increment_frames_with_detections=True)
        svc.reset()
        stats = svc.get_stats()
        assert stats.fps == 0.0
        assert stats.detections == 0
        assert stats.frames_with_detections == 0


class TestUpdateListener:
    def test_listener_receives_dict_on_update(self):
        svc = StatsService()
        received = []
        svc.set_update_listener(received.append)
        svc.update(fps=25.0)
        assert received[-1]["fps"] == 25.0

    def test_listener_fires_on_reset(self):
        svc = StatsService()
        received = []
        svc.set_update_listener(received.append)
        svc.reset()
        assert received[-1] == {
            "fps": 0.0,
            "inference_time": 0.0,
            "detections": 0,
            "frames_with_detections": 0,
        }

    def test_listener_exception_is_swallowed(self):
        svc = StatsService()

        def boom(_):
            raise RuntimeError("listener error")

        svc.set_update_listener(boom)
        # Should not propagate.
        svc.update(fps=1.0)
        assert svc.get_stats().fps == 1.0
