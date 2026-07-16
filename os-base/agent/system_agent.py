"""System metrics for the hardware agent.

Host introspection — CPU / RAM / disk / temperature / GPU — read from psutil and
Jetson sysfs. Moved verbatim from the inference-service's old
`SystemController`; it belongs with the `os` hardware agent (privileged, sees the
host `/sys`). Returned as a dict; the gRPC server maps it onto `SystemStatus`.
"""
import logging
import os
from typing import List, Optional

# noinspection PyPackageRequirements
from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import open_dbus_connection
import psutil  # in conecsa-os:base

logger = logging.getLogger(__name__)

_LOGIN1_MANAGER = DBusAddress(
    "/org/freedesktop/login1",
    bus_name="org.freedesktop.login1",
    interface="org.freedesktop.login1.Manager",
)


class SystemAgent:
    """Reads host CPU/RAM/disk/temperature/GPU metrics."""

    @staticmethod
    def _login1_call(method: str) -> None:
        """Call org.freedesktop.login1.Manager on the host system bus.

        The os-agent container bind-mounts /run/dbus/system_bus_socket, so this
        reaches host logind and requests a host-level reboot/poweroff.
        """
        conn = open_dbus_connection(bus="SYSTEM")
        try:
            # boolean arg = interactive (false => do not prompt)
            msg = new_method_call(_LOGIN1_MANAGER, method, "b", (False,))
            conn.send_and_get_reply(msg)
        finally:
            conn.close()

    @staticmethod
    def system_power(action: str) -> dict:
        """Request host shutdown/restart via systemd-logind (D-Bus)."""
        normalized = (action or "").strip().lower()
        method = {
            "shutdown": "PowerOff",
            "restart": "Reboot",
        }.get(normalized)
        if method is None:
            return {"success": False, "message": f"Unknown action: {action!r}"}
        try:
            SystemAgent._login1_call(method)
            return {"success": True, "message": f"System {normalized} requested"}
        except Exception as exc:  # noqa: BLE001
            logger.error("System power action %s failed: %s", normalized, exc)
            return {"success": False, "message": str(exc)}

    @staticmethod
    def _read_first_float(paths: List[str], scale: float = 1.0) -> Optional[float]:
        """Read first available numeric value from candidate files."""
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8") as file:
                    raw = file.read().strip()
                if not raw:
                    continue
                return float(raw) / scale
            except (FileNotFoundError, PermissionError, ValueError, OSError, TypeError):
                continue
        return None

    @staticmethod
    def _read_thermal_zone_temp(type_keywords: List[str]) -> Optional[float]:
        """Read thermal zone temp by matching type keywords (Jetson-friendly)."""
        thermal_root = "/sys/class/thermal"
        if not os.path.isdir(thermal_root):
            return None
        try:
            zones = sorted(n for n in os.listdir(thermal_root) if n.startswith("thermal_zone"))
        except OSError:
            return None

        for zone in zones:
            zone_path = os.path.join(thermal_root, zone)
            try:
                with open(os.path.join(zone_path, "type"), "r", encoding="utf-8") as file:
                    sensor_type = file.read().strip().lower()
                if not sensor_type or not any(k in sensor_type for k in type_keywords):
                    continue
                with open(os.path.join(zone_path, "temp"), "r", encoding="utf-8") as file:
                    raw_temp = file.read().strip()
                if not raw_temp:
                    continue
                temp_c = float(raw_temp)
                if temp_c > 1000:
                    temp_c = temp_c / 1000.0
                return round(temp_c, 1)
            except (FileNotFoundError, PermissionError, ValueError, OSError, TypeError):
                continue
        return None

    @staticmethod
    def _get_gpu_status() -> dict:
        """Get GPU metrics from Jetson sysfs paths if available."""
        gpu_load = SystemAgent._read_first_float([
            "/sys/class/devfreq/17000000.gpu/device/load",
            "/sys/devices/platform/17000000.gpu/load",
        ])
        if gpu_load is not None and gpu_load > 100:
            gpu_load = gpu_load / 10.0

        gpu_current_freq = SystemAgent._read_first_float([
            "/sys/class/devfreq/17000000.gpu/cur_freq",
            "/sys/devices/platform/17000000.gpu/devfreq/17000000.gpu/cur_freq",
        ], scale=1_000_000.0)

        gpu_max_freq = SystemAgent._read_first_float([
            "/sys/class/devfreq/17000000.gpu/max_freq",
            "/sys/devices/platform/17000000.gpu/devfreq/17000000.gpu/max_freq",
        ], scale=1_000_000.0)

        gpu_temperature = SystemAgent._read_thermal_zone_temp(["gpu"])

        return {
            "gpu_usage": round(gpu_load, 2) if gpu_load is not None else None,
            "gpu_temperature": gpu_temperature,
            "gpu_freq_mhz": round(gpu_current_freq, 2) if gpu_current_freq is not None else None,
            "gpu_max_freq_mhz": round(gpu_max_freq, 2) if gpu_max_freq is not None else None,
        }

    @staticmethod
    def _get_temperature() -> Optional[float]:
        """Get CPU temperature if available (sysfs first, then psutil fallback)."""
        cpu_temp = SystemAgent._read_thermal_zone_temp(["cpu"])
        if cpu_temp is not None:
            return cpu_temp
        generic_temp = SystemAgent._read_thermal_zone_temp(["thermal", "soc", "tj"])
        if generic_temp is not None:
            return generic_temp
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return None
            for entries in temps.values():
                for entry in entries:
                    current = getattr(entry, "current", None)
                    if current is None:
                        continue
                    try:
                        return round(float(current), 1)
                    except (TypeError, ValueError):
                        continue
        except Exception as error:  # noqa: BLE001
            logger.debug("Temperature not available: %s", error)
        return None

    @staticmethod
    def get_system_status() -> dict:
        """CPU / RAM / disk / temperature / GPU. Same shape the old endpoint served."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            temperature = SystemAgent._get_temperature()
            gpu_status = SystemAgent._get_gpu_status()
            return {
                "cpu_usage": round(cpu_percent, 2),
                "ram_usage": round(ram.percent, 2),
                "ram_total": ram.total,
                "ram_used": ram.used,
                "disk_usage": round(disk.percent, 2),
                "disk_total": disk.total,
                "disk_used": disk.used,
                "temperature": temperature,
                **gpu_status,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("Error getting system status: %s", e)
            return {
                "cpu_usage": 0.0, "ram_usage": 0.0, "ram_total": 0, "ram_used": 0,
                "disk_usage": 0.0, "disk_total": 0, "disk_used": 0,
                "temperature": None, "gpu_usage": None, "gpu_temperature": None,
                "gpu_freq_mhz": None, "gpu_max_freq_mhz": None,
            }
