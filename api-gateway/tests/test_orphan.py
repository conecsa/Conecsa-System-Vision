"""Unit tests for the orphaned-training watchdog (gateway/training/orphan.py)."""
import time
from types import SimpleNamespace

import grpc
import pytest

from gateway.training import orphan
from gateway.training.orphan import OrphanTracker


class FakeRpcError(grpc.RpcError):
    pass


def _clients(job_status="idle", conversions=(), broken=False):
    """A fake `clients` namespace for the watchdog's two probes."""
    def get_training(_):
        if broken:
            raise FakeRpcError()
        return SimpleNamespace(status=job_status)

    def list_conversions(_):
        if broken:
            raise FakeRpcError()
        return SimpleNamespace(
            jobs=[SimpleNamespace(status=s) for s in conversions])

    return SimpleNamespace(
        training=SimpleNamespace(GetTraining=get_training),
        model=SimpleNamespace(ListConversions=list_conversions),
    )


@pytest.fixture
def exits(monkeypatch):
    """Capture watchdog-triggered exits; returns the call-recording list."""
    calls = []

    def fake_do_exit(resume_detection):
        calls.append(resume_detection)
        return True, "resumed"

    # check_once() imports `_do_exit` from .session at call time.
    monkeypatch.setattr("gateway.training.session._do_exit", fake_do_exit)
    return calls


def _expired_tracker(monkeypatch, timeout=10.0, **clients_kw):
    """An armed tracker whose idle window is already exhausted."""
    monkeypatch.setattr(orphan, "clients", _clients(**clients_kw))
    t = OrphanTracker(timeout_sec=timeout)
    t.arm()
    monkeypatch.setattr(
        time, "monotonic", lambda base=time.monotonic(): base + timeout + 1)
    return t


class TestArming:
    def test_starts_disarmed_and_arms(self):
        t = OrphanTracker(timeout_sec=10)
        assert not t.armed
        t.arm()
        assert t.armed
        t.disarm()
        assert not t.armed

    def test_touch_returns_none_for_before_request(self):
        # A before_request handler returning non-None would short-circuit Flask.
        assert OrphanTracker(timeout_sec=10).touch() is None


class TestCheckOnce:
    def test_fires_once_and_disarms(self, monkeypatch, exits):
        t = _expired_tracker(monkeypatch)
        t.check_once()
        assert exits == [True]
        assert not t.armed
        t.check_once()
        assert exits == [True], "a disarmed tracker must not fire again"

    def test_skipped_while_disarmed(self, monkeypatch, exits):
        monkeypatch.setattr(orphan, "clients", _clients())
        t = OrphanTracker(timeout_sec=10.0)
        monkeypatch.setattr(
            time, "monotonic", lambda base=time.monotonic(): base + 100)
        t.check_once()
        assert exits == []

    def test_skipped_within_the_idle_window(self, monkeypatch, exits):
        monkeypatch.setattr(orphan, "clients", _clients())
        t = OrphanTracker(timeout_sec=3600.0)
        t.arm()
        t.check_once()
        assert exits == []
        assert t.armed

    def test_touch_resets_the_idle_window(self, monkeypatch, exits):
        monkeypatch.setattr(orphan, "clients", _clients())
        t = OrphanTracker(timeout_sec=10.0)
        t.arm()
        base = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: base + 11)
        t.touch()  # hub activity at +11s
        monkeypatch.setattr(time, "monotonic", lambda: base + 20)
        t.check_once()  # only 9s idle since the touch
        assert exits == []
        assert t.armed

    def test_skipped_while_a_job_is_active(self, monkeypatch, exits):
        t = _expired_tracker(monkeypatch, job_status="training")
        t.check_once()
        assert exits == []
        assert t.armed, "must stay armed for after the job ends"

    def test_skipped_while_a_conversion_runs(self, monkeypatch, exits):
        t = _expired_tracker(monkeypatch,
                             conversions=("converting_to_engine",))
        t.check_once()
        assert exits == []
        assert t.armed

    def test_done_conversions_do_not_block(self, monkeypatch, exits):
        t = _expired_tracker(monkeypatch, conversions=("done", "failed"))
        t.check_once()
        assert exits == [True]

    def test_probe_failure_skips_the_tick(self, monkeypatch, exits):
        t = _expired_tracker(monkeypatch, broken=True)
        t.check_once()
        assert exits == []
        assert t.armed, "unknown state → retry on the next tick"

    def test_failed_exit_stays_armed(self, monkeypatch):
        monkeypatch.setattr("gateway.training.session._do_exit",
                            lambda resume_detection: (False, "runtime busy"))
        t = _expired_tracker(monkeypatch)
        t.check_once()
        assert t.armed, "failed auto-exit must retry on the next tick"


class TestStartupRecovery:
    def test_active_job_at_boot_arms(self, monkeypatch):
        monkeypatch.setattr(orphan, "clients", _clients(job_status="training"))
        t = OrphanTracker(timeout_sec=10)
        t._recover()
        assert t.armed

    def test_idle_job_at_boot_stays_disarmed(self, monkeypatch):
        monkeypatch.setattr(orphan, "clients", _clients(job_status="done"))
        t = OrphanTracker(timeout_sec=10)
        t._recover()
        assert not t.armed

    def test_unreachable_service_at_boot_stays_disarmed(self, monkeypatch):
        monkeypatch.setattr(orphan, "clients", _clients(broken=True))
        t = OrphanTracker(timeout_sec=10)
        t._recover()
        assert not t.armed


class TestDisabled:
    def test_timeout_zero_never_starts(self):
        t = OrphanTracker(timeout_sec=0)
        t.start()  # must not spawn the watchdog thread
        import threading
        assert not any(th.name == "orphan-watchdog"
                       for th in threading.enumerate())
