"""
Thin blocking client for systemd-networkd over the system D-Bus.

The agent runs in a container with its own network namespace, so it cannot read
host interfaces from `/sys/class/net`. Instead it talks to the host's
`org.freedesktop.network1` service over the bind-mounted system bus socket
(`/run/dbus/system_bus_socket`). D-Bus auth is EXTERNAL by uid; the agent runs
as root so the host bus accepts it.
"""
import json
import logging
import socket as _socket
from typing import Any

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection

logger = logging.getLogger(__name__)

_MANAGER = DBusAddress(
    "/org/freedesktop/network1",
    bus_name="org.freedesktop.network1",
    interface="org.freedesktop.network1.Manager",
)


def _call(method: str, signature: str = "", body: tuple = ()) -> Any:
    """Open a short-lived system-bus connection and invoke a Manager method."""
    conn = open_dbus_connection(bus="SYSTEM")
    try:
        msg = new_method_call(_MANAGER, method, signature, body)
        reply = conn.send_and_get_reply(msg)
        return reply.body
    finally:
        conn.close()


def list_links() -> list[tuple[int, str]]:
    """Return [(ifindex, name), …] for every link known to networkd."""
    body = _call("ListLinks")  # -> (a(iso),)
    links = body[0] if body else []
    return [(int(ifindex), str(name)) for ifindex, name, _path in links]


def describe_link(ifindex: int) -> dict:
    """Return the parsed JSON state of a single link (DescribeLink)."""
    body = _call("DescribeLink", "i", (int(ifindex),))
    return json.loads(body[0]) if body else {}


def reload() -> None:
    """Reload .network/.netdev files (picks up newly written config)."""
    _call("Reload")


def reconfigure_link(ifindex: int) -> None:
    """Re-apply configuration to a single link after a Reload()."""
    _call("ReconfigureLink", "i", (int(ifindex),))


# ── DescribeLink JSON parsing ────────────────────────────────────────────────
#
# DescribeLink returns the same structure `networkctl --json` exposes. Field
# names are stable but address values arrive as byte arrays, so parse
# defensively and tolerate missing keys.

_AF_INET = 2


def _bytes_to_ipv4(addr: Any) -> str | None:
    """Convert a networkd address byte array to dotted-quad, IPv4 only."""
    try:
        if isinstance(addr, (list, tuple)) and len(addr) == 4:
            return ".".join(str(int(b) & 0xFF) for b in addr)
        if isinstance(addr, (bytes, bytearray)) and len(addr) == 4:
            return _socket.inet_ntoa(bytes(addr))
    except Exception:  # noqa: BLE001 - defensive parse
        pass
    return None


def parse_ipv4(link: dict) -> dict:
    """Extract IPv4 method/address/prefix/gateway/dns from a DescribeLink dict.

    Returns keys: method ("auto"|"static"), address, prefix, gateway, dns(list).
    method is derived from the address ConfigSource (DHCP4 → auto, static →
    static); callers may override using the presence of a managed static file.
    """
    out: dict = {
        "method": "auto",
        "address": "",
        "prefix": 0,
        "gateway": "",
        "dns": [],
    }

    for entry in link.get("Addresses", []) or []:
        if entry.get("Family") != _AF_INET:
            continue
        ip = _bytes_to_ipv4(entry.get("Address"))
        if not ip or ip.startswith("169.254."):  # skip link-local
            continue
        out["address"] = ip
        out["prefix"] = int(entry.get("PrefixLength", 0) or 0)
        if str(entry.get("ConfigSource", "")).lower() == "static":
            out["method"] = "static"
        break

    # Gateway: first IPv4 entry under Gateways or default Routes.
    for entry in link.get("Gateways", []) or []:
        if entry.get("Family") == _AF_INET:
            gw = _bytes_to_ipv4(entry.get("Address"))
            if gw:
                out["gateway"] = gw
                break
    if not out["gateway"]:
        for route in link.get("Routes", []) or []:
            if route.get("Family") == _AF_INET and route.get("DestinationPrefixLength", 1) == 0:
                gw = _bytes_to_ipv4(route.get("Gateway"))
                if gw:
                    out["gateway"] = gw
                    break

    for entry in link.get("DNS", []) or []:
        if entry.get("Family") == _AF_INET:
            dns = _bytes_to_ipv4(entry.get("Address"))
            if dns:
                out["dns"].append(dns)

    return out
