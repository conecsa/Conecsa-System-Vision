"""
gRPC server for the hardware-management agent.

Serves HardwareService (proto/hardware.proto). Network/Wi-Fi RPCs are backed by
NetworkAgent; GPIO RPCs are placeholders until a later migration.
"""
import logging
import os
import sys
from concurrent import futures

import grpc

# The generated *_pb2_grpc module does a flat `import hardware_pb2`, so the
# compiled proto directory must be on sys.path.
_PROTO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proto")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import hardware_pb2 as pb          # noqa: E402
import hardware_pb2_grpc as pb_grpc  # noqa: E402

from .clocks_agent import pin_performance_clocks  # noqa: E402
from .gpio_agent import GpioAgent  # noqa: E402
from .network_agent import NetworkAgent  # noqa: E402
from .system_agent import SystemAgent  # noqa: E402

logger = logging.getLogger(__name__)

LISTEN_ADDR = os.environ.get("HARDWARE_AGENT_LISTEN", "0.0.0.0:50051")


def _iface_config_pb(cfg: dict) -> pb.InterfaceConfig:
    """Convert a NetworkAgent interface dict to an ``InterfaceConfig`` message."""
    return pb.InterfaceConfig(
        name=cfg.get("name", ""),
        method=cfg.get("method", "auto"),
        address=cfg.get("address", ""),
        prefix=int(cfg.get("prefix", 0) or 0),
        gateway=cfg.get("gateway", ""),
        dns=list(cfg.get("dns", []) or []),
        present=bool(cfg.get("present", False)),
    )


class HardwareServicer(pb_grpc.HardwareServiceServicer):
    """gRPC HardwareService implementation.

    Each RPC is a thin adapter that delegates to the backing agent
    (:class:`NetworkAgent`, :class:`GpioAgent`, :class:`SystemAgent`) and maps
    the result to/from the ``hardware.proto`` messages.
    """

    def __init__(self, gpio: GpioAgent):
        self.network = NetworkAgent()
        self.gpio = gpio

    # ── Network / IP ────────────────────────────────────────────────────────────

    def GetNetworkConfig(self, request, context):
        """RPC: return the wired + Wi-Fi IPv4 config and Wi-Fi status."""
        cfg = self.network.get_network_config()
        status = cfg.get("wifi_status", {})
        return pb.NetworkConfig(
            wired=_iface_config_pb(cfg.get("wired", {})),
            wifi=_iface_config_pb(cfg.get("wifi", {})),
            wifi_status=pb.WifiStatus(
                ssid=status.get("ssid", ""),
                state=status.get("state", ""),
                signal=int(status.get("signal", 0) or 0),
            ),
        )

    def SetIpConfig(self, request, context):
        """RPC: apply an IPv4 config (auto/static) to the wired or Wi-Fi link."""
        interface = "wifi" if request.interface == pb.WIFI else "wired"
        res = self.network.set_ip_config(
            interface=interface,
            method=request.method,
            address=request.address,
            prefix=request.prefix,
            gateway=request.gateway,
            dns=list(request.dns),
        )
        return pb.Result(success=res["success"], message=res["message"])

    # ── Wi-Fi ─────────────────────────────────────────────────────────────────────

    def ScanWifi(self, request, context):
        """RPC: scan for Wi-Fi networks."""
        nets = self.network.scan_wifi()
        return pb.WifiScanResult(networks=[
            pb.WifiNetwork(
                ssid=n["ssid"], signal=int(n["signal"]), security=n["security"],
                in_use=n["in_use"], saved=n["saved"],
            ) for n in nets
        ])

    def ConnectWifi(self, request, context):
        """RPC: connect to a Wi-Fi network by ``{ssid, password}``."""
        res = self.network.connect_wifi(request.ssid, request.password)
        return pb.WifiConnectResult(
            success=res["success"], state=res["state"], message=res["message"],
        )

    def ForgetWifi(self, request, context):
        """RPC: remove a saved Wi-Fi network by ``{ssid}``."""
        res = self.network.forget_wifi(request.ssid)
        return pb.Result(success=res["success"], message=res["message"])

    # ── GPIO (config/output ops; per-frame trigger gate uses shared memory) ──────

    def GetGpioStatus(self, request, context):
        """RPC: return GPIO availability, trigger mode and output pin levels."""
        st = self.gpio.get_status()
        return pb.GpioStatus(
            available=st["available"],
            enabled=st["enabled"],
            pins=[pb.GpioPinState(pin=p, level=v) for p, v in st["pins"].items()],
        )

    def SetGpioTrigger(self, request, context):
        """RPC: enable/disable GPIO trigger mode."""
        res = self.gpio.set_enabled(request.enabled)
        return pb.Result(success=res["success"], message=res["message"])

    def SetGpioPin(self, request, context):
        """RPC: drive a single output pin HIGH/LOW."""
        res = self.gpio.set_pin(request.pin, request.level)
        return pb.Result(success=res["success"], message=res["message"])

    # ── System metrics ────────────────────────────────────────────────────────

    def GetSystemStatus(self, request, context):
        """RPC: return host metrics (CPU/RAM/disk + optional temp/GPU sensors)."""
        st = SystemAgent.get_system_status()
        msg = pb.SystemStatus(
            cpu_usage=st["cpu_usage"],
            ram_usage=st["ram_usage"],
            ram_total=int(st["ram_total"]),
            ram_used=int(st["ram_used"]),
            disk_usage=st["disk_usage"],
            disk_total=int(st["disk_total"]),
            disk_used=int(st["disk_used"]),
        )
        # proto3 `optional` floats: only set when the metric is available so the
        # gateway relays JSON `null` for absent sensors.
        for field in ("temperature", "gpu_usage", "gpu_temperature",
                      "gpu_freq_mhz", "gpu_max_freq_mhz"):
            value = st.get(field)
            if value is not None:
                setattr(msg, field, float(value))
        return msg

    # ── System power ─────────────────────────────────────────────────────────

    def SystemPower(self, request, context):
        """RPC: perform a host power action (e.g. shutdown/reboot)."""
        result = SystemAgent.system_power(request.action)
        return pb.SystemPowerResult(
            success=bool(result.get("success", False)),
            message=str(result.get("message", "")),
        )


def serve() -> None:
    """Pin performance clocks, start the GPIO agent, and serve HardwareService.

    Blocks until termination, then cleans up the GPIO agent.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    # Pin the Jetson to performance clocks first — the dynamic governors leave the
    # GPU at its minimum for the bursty inference workload, ~2x-ing latency.
    pin_performance_clocks()
    # GpioAgent initialises the GPIO hardware and starts the shared-memory poll
    # loop before the server accepts calls.
    gpio = GpioAgent()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    pb_grpc.add_HardwareServiceServicer_to_server(HardwareServicer(gpio), server)
    server.add_insecure_port(LISTEN_ADDR)
    server.start()
    logger.info("Hardware agent gRPC server listening on %s", LISTEN_ADDR)
    try:
        server.wait_for_termination()
    finally:
        gpio.cleanup()
