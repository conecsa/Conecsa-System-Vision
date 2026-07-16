"""Thin gRPC clients to the `os` hardware agent (network / Wi-Fi / GPIO).

These mirror the translation the monolith's NetworkService/GPIOService did, so
the gateway's /network/* and /gpio/* endpoints return byte-identical JSON. The
per-frame GPIO hot path (trigger gate / count output) stays in inference-service
over SHM — the gateway only does the config-style RPCs the UI needs.
"""
import logging
from typing import Any, List, Optional

import grpc

from .grpc_clients import clients, hw

logger = logging.getLogger(__name__)

_TIMEOUT_DEFAULT = 12
_TIMEOUT_SCAN = 20
_TIMEOUT_CONNECT = 30

# Static pin map (matches os-base/agent/gpio_shm.py); the live trigger pin level is
# only readable over the GPIO SHM, which stays on the inference side, so the
# gateway reports it as null.
_TRIGGER_INPUT_PIN = 7
_OUTPUT_PINS = [29, 31, 33]


def _iface_to_dict(cfg) -> dict:
    """Serialize an InterfaceConfig message to the gateway's JSON shape."""
    return {
        "name": cfg.name,
        "method": cfg.method or "auto",
        "address": cfg.address or None,
        "prefix": cfg.prefix or None,
        "gateway": cfg.gateway or None,
        "dns": list(cfg.dns),
        "present": cfg.present,
    }


# ── Network ───────────────────────────────────────────────────────────────────

def get_network_config() -> dict:
    """Fetch the wired + Wi-Fi config and Wi-Fi status from the os agent."""
    resp = clients.hardware.GetNetworkConfig(hw.Empty(), timeout=_TIMEOUT_DEFAULT)
    return {
        "wired": _iface_to_dict(resp.wired),
        "wifi": _iface_to_dict(resp.wifi),
        "wifi_status": {
            "ssid": resp.wifi_status.ssid,
            "state": resp.wifi_status.state,
            "signal": resp.wifi_status.signal,
        },
    }


def set_network_config(
    interface: str,
    method: str,
    address: Optional[str] = None,
    prefix: Optional[int] = None,
    gateway: Optional[str] = None,
    dns: Optional[List[str]] = None,
) -> dict:
    """Apply an IPv4 config (auto/static) to an interface via the os agent."""
    iface = hw.WIFI if str(interface).lower() == "wifi" else hw.WIRED
    req = hw.IpConfigRequest(
        interface=iface,
        method=method,
        address=address or "",
        prefix=int(prefix) if prefix else 0,
        gateway=gateway or "",
        dns=dns or [],
    )
    resp = clients.hardware.SetIpConfig(req, timeout=_TIMEOUT_DEFAULT)
    return {"success": resp.success, "message": resp.message}


def scan_wifi() -> dict:
    """Return available Wi-Fi networks (via the os agent)."""
    resp = clients.hardware.ScanWifi(hw.Empty(), timeout=_TIMEOUT_SCAN)
    return {
        "networks": [
            {
                "ssid": n.ssid,
                "signal": n.signal,
                "security": n.security,
                "in_use": n.in_use,
                "saved": n.saved,
            }
            for n in resp.networks
        ]
    }


def connect_wifi(ssid: str, password: str) -> dict:
    """Connect to a Wi-Fi network by ``{ssid, password}`` (via the os agent)."""
    req = hw.WifiConnectRequest(ssid=ssid, password=password or "")
    resp = clients.hardware.ConnectWifi(req, timeout=_TIMEOUT_CONNECT)
    return {"success": resp.success, "state": resp.state, "message": resp.message}


def forget_wifi(ssid: str) -> dict:
    """Remove a saved Wi-Fi network by ``ssid`` (via the os agent)."""
    resp = clients.hardware.ForgetWifi(hw.WifiForgetRequest(ssid=ssid), timeout=_TIMEOUT_DEFAULT)
    return {"success": resp.success, "message": resp.message}


# ── GPIO ──────────────────────────────────────────────────────────────────────

def get_gpio_status() -> dict:
    """Return GPIO availability/trigger + output pin levels (via the os agent)."""
    try:
        st = clients.hardware.GetGpioStatus(hw.Empty(), timeout=10)
        available, enabled = st.available, st.enabled
        pin_states = {str(p.pin): p.level for p in st.pins}
    except grpc.RpcError as exc:
        logger.error("GPIO status RPC failed: %s",
                     exc.details() if hasattr(exc, "details") else exc)
        available, enabled = False, False
        pin_states = {str(p): False for p in _OUTPUT_PINS}
    return {
        "gpio_available": available,
        "gpio_enabled": enabled,
        "trigger_pin": _TRIGGER_INPUT_PIN,
        "output_pins": _OUTPUT_PINS,
        "pin_states": pin_states,
        "trigger_state": None,
    }


def set_gpio_enabled(enabled: bool) -> None:
    """Enable/disable GPIO trigger mode; raises on failure (via the os agent)."""
    resp = clients.hardware.SetGpioTrigger(hw.GpioTriggerRequest(enabled=enabled), timeout=10)
    if not resp.success:
        raise RuntimeError(resp.message or "failed to set GPIO trigger")


def set_gpio_pin(pin: int, level: bool) -> None:
    """Drive a single output pin HIGH/LOW; raises on failure (via the os agent)."""
    resp = clients.hardware.SetGpioPin(hw.GpioPinRequest(pin=pin, level=level), timeout=10)
    if not resp.success:
        raise RuntimeError(resp.message or f"failed to set GPIO pin {pin}")


# ── System metrics ────────────────────────────────────────────────────────────

_SYS_OPTIONAL = ("temperature", "gpu_usage", "gpu_temperature",
                 "gpu_freq_mhz", "gpu_max_freq_mhz")


def get_system_status() -> dict:
    """CPU/RAM/disk/temperature/GPU from the os agent. Same JSON shape the old
    inference endpoint served — absent optional sensors come back as ``null``."""
    s = clients.hardware.GetSystemStatus(hw.Empty(), timeout=_TIMEOUT_DEFAULT)
    out = {
        "cpu_usage": s.cpu_usage,
        "ram_usage": s.ram_usage,
        "ram_total": s.ram_total,
        "ram_used": s.ram_used,
        "disk_usage": s.disk_usage,
        "disk_total": s.disk_total,
        "disk_used": s.disk_used,
    }
    for field in _SYS_OPTIONAL:
        out[field] = getattr(s, field) if s.HasField(field) else None
    return out


# ── System power ──────────────────────────────────────────────────────────────

def system_power(action: str) -> dict:
    """Send a shutdown or restart command to the host via the hardware agent.

    ``action`` must be ``"shutdown"`` or ``"restart"``.
    """
    req = hw.SystemPowerRequest(action=action)
    resp = clients.hardware.SystemPower(req, timeout=_TIMEOUT_DEFAULT)
    return {"success": resp.success, "message": resp.message}
