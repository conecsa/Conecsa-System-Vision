"""
Direct client for the wpa_supplicant control interface.

wpa_supplicant runs on the host with its control socket at
`/run/wpa_supplicant/<iface>`. That directory is bind-mounted into the agent
container. We do NOT use the `wpa_cli` binary: it creates its reply socket under
`/tmp`, which lives in the container's mount namespace, so the host daemon's
`sendto()` to that path never arrives and every command times out.

Instead we speak the (simple) control protocol over an AF_UNIX/SOCK_DGRAM socket
and bind our reply socket *inside* the shared `/run/wpa_supplicant` mount — the
same path on host and container — so the daemon can reach it. Commands are the
raw upper-case control verbs (STATUS, SCAN, SCAN_RESULTS, …).

NOTE: never log PSKs — SET_NETWORK psk arguments are not echoed to the logger.
"""
import itertools
import logging
import os
import socket
import time

logger = logging.getLogger(__name__)

CTRL_DIR = "/run/wpa_supplicant"

_counter = itertools.count()


class WpaError(RuntimeError):
    """A wpa_supplicant control command failed, timed out, or returned FAIL."""


class WpaCli:
    """Stateless control-interface client for a single wireless interface.

    (Name kept for call-site compatibility; it no longer shells out to wpa_cli.)
    """

    def __init__(self, iface: str):
        self.iface = iface

    # ── transport ───────────────────────────────────────────────────────────────

    def _cmd(self, command: str, timeout: float = 5.0) -> str:
        """Send one control verb and return the daemon's raw reply.

        Binds a short-lived reply socket inside the shared ``/run/wpa_supplicant``
        mount so the host daemon can reach it. Raises :class:`WpaError` on
        timeout or socket error.
        """
        daemon = os.path.join(CTRL_DIR, self.iface)
        if not os.path.exists(daemon):
            raise WpaError(f"control socket {daemon} not found")
        local = os.path.join(CTRL_DIR, f".conecsa-{os.getpid()}-{next(_counter)}")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            try:
                os.unlink(local)
            except OSError:
                pass
            sock.bind(local)
            sock.settimeout(timeout)
            sock.connect(daemon)
            sock.send(command.encode())
            return sock.recv(32768).decode(errors="replace")
        except socket.timeout as exc:
            raise WpaError(f"timeout running '{command.split()[0]}'") from exc
        except OSError as exc:
            raise WpaError(f"control error on '{command.split()[0]}': {exc}") from exc
        finally:
            sock.close()
            try:
                os.unlink(local)
            except OSError:
                pass

    def _cmd_ok(self, command: str, timeout: float = 5.0) -> None:
        """Run *command* and raise :class:`WpaError` unless it replies ``OK``."""
        reply = self._cmd(command, timeout=timeout).strip()
        last = reply.splitlines()[-1].strip() if reply else ""
        if last != "OK":
            raise WpaError(f"'{command.split()[0]}' returned {reply or 'no reply'}")

    # ── status / scan ─────────────────────────────────────────────────────────────

    def status(self) -> dict[str, str]:
        """Return the parsed STATUS key/value map (ssid, wpa_state, …)."""
        out = self._cmd("STATUS")
        result: dict[str, str] = {}
        for line in out.splitlines():
            key, sep, value = line.partition("=")
            if sep:
                result[key.strip()] = value.strip()
        return result

    def scan(self) -> list[dict]:
        """Trigger a scan and return parsed results (one entry per BSS)."""
        try:
            self._cmd("SCAN")
        except WpaError:
            pass  # FAIL-BUSY when a scan is already running — reuse results
        time.sleep(2.0)
        out = self._cmd("SCAN_RESULTS")
        networks: list[dict] = []
        for line in out.splitlines()[1:]:  # skip header row
            parts = line.split("\t")
            if len(parts) < 5:
                continue
            _bssid, _freq, signal, flags, ssid = parts[0], parts[1], parts[2], parts[3], parts[4]
            if not ssid:
                continue
            networks.append({
                "ssid": ssid,
                "signal": _safe_int(signal),
                "security": _security_from_flags(flags),
            })
        return networks

    def list_networks(self) -> list[dict]:
        """Return saved networks as ``{id, ssid, flags}`` dicts."""
        out = self._cmd("LIST_NETWORKS")
        nets: list[dict] = []
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            nets.append({
                "id": parts[0].strip(),
                "ssid": parts[1].strip(),
                "flags": parts[3] if len(parts) > 3 else "",
            })
        return nets

    # ── connect / forget ───────────────────────────────────────────────────────────

    def find_network_id(self, ssid: str) -> str | None:
        """Return the saved-network id for *ssid*, or ``None`` if not saved."""
        for net in self.list_networks():
            if net["ssid"] == ssid:
                return net["id"]
        return None

    def add_network(self) -> str:
        """Create an empty network and return its id."""
        reply = self._cmd("ADD_NETWORK").strip()
        last = reply.splitlines()[-1].strip() if reply else ""
        if not last.isdigit():
            raise WpaError(f"ADD_NETWORK returned {reply or 'no reply'}")
        return last

    def set_network(self, net_id: str, key: str, value: str) -> None:
        """Set one network variable (SET_NETWORK). PSK values are never logged."""
        self._cmd_ok(f"SET_NETWORK {net_id} {key} {value}")

    def get_network_int(self, net_id: str, key: str, default: int = 0) -> int:
        """Read a numeric network variable (e.g. priority). Unset vars reply
        FAIL, which maps to `default`."""
        reply = self._cmd(f"GET_NETWORK {net_id} {key}").strip()
        if not reply or reply.splitlines()[-1].strip() == "FAIL":
            return default
        return _safe_int(reply.strip().strip('"'), default)

    def select_network(self, net_id: str) -> None:
        """Select *net_id* and disable the others (SELECT_NETWORK)."""
        self._cmd_ok(f"SELECT_NETWORK {net_id}")

    def enable_network(self, net_id: str) -> None:
        """Mark *net_id* eligible for (re)association (ENABLE_NETWORK)."""
        self._cmd_ok(f"ENABLE_NETWORK {net_id}")

    def remove_network(self, net_id: str) -> None:
        """Delete a saved network (REMOVE_NETWORK)."""
        self._cmd_ok(f"REMOVE_NETWORK {net_id}")

    def save_config(self) -> None:
        """Persist the in-memory config to disk (SAVE_CONFIG)."""
        self._cmd_ok("SAVE_CONFIG")

    def reconfigure(self) -> None:
        """Re-read the on-disk config and re-associate. Used to roll back a
        failed connect attempt: since we never SAVE_CONFIG on failure, the file
        still describes the previously-working network(s), so this restores the
        device to its prior connection without stranding it."""
        self._cmd_ok("RECONFIGURE")

    def enable_all(self) -> None:
        """Re-enable every saved network (SELECT_NETWORK disables the others),
        so all known networks stay eligible for auto-reconnect on reboot."""
        for net in self.list_networks():
            try:
                self.enable_network(net["id"])
            except WpaError:
                pass


def _safe_int(value: str, default: int = 0) -> int:
    """Parse *value* as int, returning *default* on failure."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _security_from_flags(flags: str) -> str:
    """Map a scan_results flags string to a coarse security label."""
    f = flags.upper()
    if "SAE" in f or "WPA3" in f:
        return "WPA3"
    if "WPA2" in f or "RSN" in f:
        return "WPA2"
    if "WPA" in f:
        return "WPA2"
    if "WEP" in f:
        return "WEP"
    return "OPEN"
