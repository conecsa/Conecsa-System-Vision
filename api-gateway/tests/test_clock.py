"""Unit tests for the hub-driven clock correction (gateway/clock.py)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import grpc
import pytest
from flask import Flask
from gateway import clock


class _FakeHardware:
    """Stand-in for the `os` agent stub: records calls, replays a canned reply."""

    def __init__(self, success=True, message="ok", raises=None):
        self.calls = []
        self._reply = SimpleNamespace(success=success, message=message)
        self._raises = raises

    def SetSystemTime(self, request, timeout=None):  # noqa: N802 — gRPC stub name
        self.calls.append((request, timeout))
        if self._raises is not None:
            raise self._raises
        return self._reply


@pytest.fixture
def hardware(monkeypatch):
    """Install a fake hardware stub and clear the rate limiter."""
    def _install(**kwargs):
        fake = _FakeHardware(**kwargs)
        monkeypatch.setattr(clock.clients, "hardware", fake)
        monkeypatch.setattr(clock, "_last_attempt", {"at": float("-inf")})
        return fake
    return _install


class _FailedCall(grpc.RpcError, grpc.Call):
    """A failed unary call the way grpcio raises it: an RpcError that is also a
    Call, so the handler can ask it for its status code."""

    def __init__(self, code: grpc.StatusCode):
        super().__init__()
        self._code = code

    def code(self):
        return self._code

    def details(self):
        return self._code.name

    def initial_metadata(self):
        return ()

    def trailing_metadata(self):
        return ()

    def is_active(self):
        return False

    def time_remaining(self):
        return 0.0

    def cancel(self):
        return False

    def add_callback(self, callback):
        return False


def _rpc_error(code: grpc.StatusCode) -> grpc.RpcError:
    return _FailedCall(code)


def _stamp(delta_seconds: float) -> str:
    """An RFC 3339 stamp *delta_seconds* away from now, as the hub sends it."""
    moment = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TestParseHubTime:
    def test_parses_the_z_suffix_the_hub_sends(self):
        parsed = clock.parse_hub_time("2026-08-03T10:00:00.000Z")
        assert parsed == datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)

    def test_normalizes_an_offset_to_utc(self):
        parsed = clock.parse_hub_time("2026-08-03T07:00:00-03:00")
        assert parsed == datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)

    def test_naive_stamp_is_read_as_utc(self):
        parsed = clock.parse_hub_time("2026-08-03T10:00:00")
        assert parsed == datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("raw", [None, "", "   ", "not-a-date"])
    def test_rejects_junk(self, raw):
        assert clock.parse_hub_time(raw) is None


class TestShouldStep:
    def test_ignores_small_drift(self):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
        assert clock.should_step(now + timedelta(seconds=5), now) is False

    @pytest.mark.parametrize("offset", [3600, -3600])
    def test_steps_in_both_directions(self, offset):
        now = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)
        assert clock.should_step(now + timedelta(seconds=offset), now) is True


class TestApplyHubTime:
    def test_sends_the_hub_time_to_the_hardware_agent(self, hardware):
        fake = hardware()
        assert clock.apply_hub_time(_stamp(7200), "pairing") is True
        (request, timeout), = fake.calls
        assert request.source == "pairing"
        assert timeout == clock._RPC_TIMEOUT_SEC
        expected = (datetime.now(timezone.utc) + timedelta(seconds=7200)).timestamp()
        assert abs(request.epoch_millis / 1000.0 - expected) < 5

    def test_no_call_when_the_clock_is_already_right(self, hardware):
        fake = hardware()
        assert clock.apply_hub_time(_stamp(1), "hub-poll") is False
        assert fake.calls == []

    def test_no_call_for_an_unparseable_stamp(self, hardware):
        fake = hardware()
        assert clock.apply_hub_time("yesterday", "hub-poll") is False
        assert fake.calls == []

    def test_rate_limits_the_poll_path(self, hardware):
        fake = hardware(success=False, message="agent down")
        assert clock.apply_hub_time(_stamp(7200), "hub-poll") is False
        assert clock.apply_hub_time(_stamp(7200), "hub-poll") is False
        assert len(fake.calls) == 1, "the 2s poll must not hammer the agent"

    def test_pairing_bypasses_the_rate_limit(self, hardware):
        fake = hardware()
        clock.apply_hub_time(_stamp(7200), "hub-poll")
        assert clock.apply_hub_time(_stamp(7200), "pairing", force=True) is True
        assert len(fake.calls) == 2

    def test_pairing_records_the_floor_even_with_a_correct_clock(self, hardware):
        fake = hardware()
        # Accepting a time is what persists the boot-time clock floor, so the
        # pairing step must not be skipped just because the drift is small.
        assert clock.apply_hub_time(_stamp(1), "pairing", force=True) is True
        assert len(fake.calls) == 1

    def test_reports_a_rejected_step(self, hardware):
        hardware(success=False, message="older than the persisted floor")
        assert clock.apply_hub_time(_stamp(-7200), "hub-poll") is False

    def test_survives_an_unreachable_agent(self, hardware):
        hardware(raises=RuntimeError("channel closed"))
        # Never propagates: this runs inline on the hub's request.
        assert clock.apply_hub_time(_stamp(7200), "hub-poll") is False


class TestStepClock:
    """The pairing path needs to know *why* a step did not land: an agent that
    refused is fatal, an agent that is not there (development host) is not."""

    def test_applied(self, hardware):
        hardware()
        assert clock.step_clock(_stamp(7200), "pairing", force=True) is clock.StepOutcome.APPLIED

    def test_a_refusal_is_rejected(self, hardware):
        hardware(success=False, message="older than the persisted floor")
        assert clock.step_clock(_stamp(-7200), "pairing", force=True) is clock.StepOutcome.REJECTED

    @pytest.mark.parametrize("code", [grpc.StatusCode.UNAVAILABLE,
                                      grpc.StatusCode.DEADLINE_EXCEEDED])
    def test_no_agent_is_unreachable(self, hardware, code):
        hardware(raises=_rpc_error(code))
        assert clock.step_clock(_stamp(7200), "pairing", force=True) is clock.StepOutcome.UNREACHABLE

    def test_an_agent_error_is_rejected_not_unreachable(self, hardware):
        # The agent answered — with a failure. Only "nobody listening" is
        # allowed to wave a pairing through without a clock.
        hardware(raises=_rpc_error(grpc.StatusCode.INTERNAL))
        assert clock.step_clock(_stamp(7200), "pairing", force=True) is clock.StepOutcome.REJECTED

    def test_a_non_grpc_failure_is_rejected(self, hardware):
        hardware(raises=RuntimeError("channel closed"))
        assert clock.step_clock(_stamp(7200), "pairing", force=True) is clock.StepOutcome.REJECTED

    def test_junk_and_small_drift_are_skipped(self, hardware):
        fake = hardware()
        assert clock.step_clock("yesterday", "hub-poll") is clock.StepOutcome.SKIPPED
        assert clock.step_clock(_stamp(1), "hub-poll") is clock.StepOutcome.SKIPPED
        assert fake.calls == []


class TestSyncFromRequestHeaders:
    """The header only counts on a request the nginx terminator verified."""

    from conftest import TERMINATOR_IP

    @pytest.fixture(autouse=True)
    def _pin_terminator(self, trusted_proxy):
        """Delegates to the shared conftest fixture."""

    def _ctx(self, remote_addr, headers):
        return Flask(__name__).test_request_context(
            "/api/v1/status", headers=headers,
            environ_base={"REMOTE_ADDR": remote_addr})

    def test_applies_a_verified_hub_stamp(self, hardware):
        fake = hardware()
        headers = {"X-Conecsa-Client-Verify": "SUCCESS",
                   clock.HUB_TIME_HEADER: _stamp(7200)}
        with self._ctx(self.TERMINATOR_IP, headers) as ctx:
            clock.sync_from_request_headers(ctx.request.headers)
        assert len(fake.calls) == 1

    def test_ignores_a_stamp_from_another_container(self, hardware):
        fake = hardware()
        headers = {"X-Conecsa-Client-Verify": "SUCCESS",
                   clock.HUB_TIME_HEADER: _stamp(7200)}
        with self._ctx("172.20.0.5", headers) as ctx:
            clock.sync_from_request_headers(ctx.request.headers)
        assert fake.calls == []

    def test_ignores_a_request_without_the_header(self, hardware):
        fake = hardware()
        with self._ctx(self.TERMINATOR_IP,
                       {"X-Conecsa-Client-Verify": "SUCCESS"}) as ctx:
            clock.sync_from_request_headers(ctx.request.headers)
        assert fake.calls == []
