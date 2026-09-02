"""Hub-driven clock correction.

The Jetson has no RTC battery, so on a site with no internet (the image pins
public NTP servers and deliberately ignores the DHCP NTP option) it can boot
with a clock older than the hub CA's `not_before`. nginx then rejects the hub's
client certificate as "not yet valid" and the device is offline for good — right
after a pairing that appeared to succeed, because pairing runs on the TOFU
channel where neither side validates anything.

So the hub relays its own wall clock and this module applies it:

* at pairing, inside ``/enroll/complete`` (the one moment a hub can reach a
  device whose clock is wrong), before the certificates are installed;
* afterwards, from the ``X-Conecsa-Hub-Time`` header the hub stamps on its
  status polls — accepted only from a request the nginx terminator verified,
  so no other container on the compose network can move the clock.

Setting the clock is a host operation: this module only decides *whether* to
step and delegates to the privileged `os` agent over gRPC, the same way network
and GPIO writes are delegated.
"""
import enum
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import grpc

from .config import settings
from .grpc_clients import clients, hw
from .helpers import _hub_verified

logger = logging.getLogger(__name__)

# Set by the hub on every mTLS status poll (RFC 3339, UTC).
HUB_TIME_HEADER = "X-Conecsa-Hub-Time"

# Short deadline: this runs inline on the hub's 2s status poll, and a clock we
# failed to set is retried on the next one anyway.
_RPC_TIMEOUT_SEC = 3.0

# time.monotonic() of the last attempt — monotonic on purpose, so stepping the
# wall clock cannot disable or spin the rate limiter. Held in a mutable box
# rather than rebound through `global`.
_last_attempt = {"at": float("-inf")}
_lock = threading.Lock()


def parse_hub_time(raw: Optional[str]) -> Optional[datetime]:
    """Parse an RFC 3339 timestamp into an aware UTC datetime, or ``None``."""
    if not raw:
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        # Python 3.10's fromisoformat does not accept the military zone suffix.
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        logger.debug("clock: unparseable hub time %r", raw)
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def should_step(hub_time: datetime, now: Optional[datetime] = None) -> bool:
    """Whether *hub_time* is far enough from the local clock to be worth setting."""
    now = now or datetime.now(timezone.utc)
    return abs((hub_time - now).total_seconds()) >= settings.CLOCK_SYNC_THRESHOLD_SEC


def _rate_limited() -> bool:
    """Consume a rate-limit slot; ``True`` when the caller must back off."""
    with _lock:
        now = time.monotonic()
        if now - _last_attempt["at"] < settings.CLOCK_SYNC_MIN_INTERVAL_SEC:
            return True
        _last_attempt["at"] = now
        return False


class StepOutcome(enum.Enum):
    """What became of one attempt to adopt the hub's clock."""

    APPLIED = "applied"          # the agent stepped the clock
    SKIPPED = "skipped"          # nothing to do: junk stamp, small drift, rate limit
    REJECTED = "rejected"        # the agent refused (below the floor, settime failed)
    UNREACHABLE = "unreachable"  # no hardware agent answered at all


# gRPC codes that mean "nobody is listening", as opposed to an answer we did not
# like. A development host runs the gateway without the Jetson-only `os` agent
# (docker-compose.dev.yml keeps `os-base` as a bare volume owner; scripts/dev.sh
# never starts it), so this is a normal condition there.
_UNREACHABLE_CODES = (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)


def step_clock(raw: Optional[str], source: str, force: bool = False) -> StepOutcome:
    """Set the host clock from *raw* when it differs materially. Never raises.

    ``force`` for the pairing path: it happens once, and it must go through even
    when the drift is small, because accepting a time is also what persists the
    clock floor the host restores at boot (see os-base/agent/time_agent.py). A
    device paired with an already-correct clock would otherwise have no floor
    until the save timer next fires.

    The outcome tells an agent that *refused* apart from an agent that is not
    there: the pairing path must abort on the former (a wrong clock strands the
    device behind mTLS) but has nothing to gain from failing on the latter.
    """
    hub_time = parse_hub_time(raw)
    if hub_time is None:
        return StepOutcome.SKIPPED
    if not force and not should_step(hub_time):
        return StepOutcome.SKIPPED
    if not force and _rate_limited():
        return StepOutcome.SKIPPED

    epoch_millis = int(hub_time.timestamp() * 1000)
    try:
        result = clients.hardware.SetSystemTime(
            hw.SystemTimeRequest(epoch_millis=epoch_millis, source=source),
            timeout=_RPC_TIMEOUT_SEC,
        )
    except grpc.RpcError as ex:
        code = ex.code() if isinstance(ex, grpc.Call) else None
        if code in _UNREACHABLE_CODES:
            logger.warning("clock: hardware agent unreachable (%s)", code)
            return StepOutcome.UNREACHABLE
        logger.warning("clock: time step failed: %s", ex)
        return StepOutcome.REJECTED
    except Exception as ex:  # noqa: BLE001 — best-effort: never fail the hub's call
        logger.warning("clock: time step failed: %s", ex)
        return StepOutcome.REJECTED
    if not result.success:
        logger.warning("clock: time step rejected: %s", result.message)
        return StepOutcome.REJECTED
    logger.info("clock: %s", result.message)
    return StepOutcome.APPLIED


def apply_hub_time(raw: Optional[str], source: str, force: bool = False) -> bool:
    """Boolean form of :func:`step_clock` for callers that only need "did it land"."""
    return step_clock(raw, source, force) is StepOutcome.APPLIED


def sync_from_request_headers(headers) -> None:
    """Flask ``before_request`` hook: honour the hub's clock stamp.

    Only acts on a request the nginx terminator verified as coming from the
    paired hub (:func:`_hub_verified`), so the header cannot be forged by
    another container on the compose network.
    """
    raw = headers.get(HUB_TIME_HEADER)
    if not raw or not _hub_verified():
        return
    apply_hub_time(raw, "hub-poll")
