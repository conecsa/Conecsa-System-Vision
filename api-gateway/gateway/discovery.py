"""mDNS advertising so conecsa-hub-vision can discover this device passively.

Registers a ``_conecsa._tcp.local.`` service carrying the device identity and the
ports the hub needs (the device web UI and the api-gateway). The hub browses for
this service and never probes the device directly.

Deployment note: mDNS is link-local multicast. For the advertisement to reach
the LAN, the api-gateway container must be able to emit multicast on the LAN
(e.g. host networking / macvlan). On the default bridge network it will not
propagate — in that case advertise from the host instead (see the avahi service
example in ``api-gateway/deploy/conecsa-hub.avahi.service``). Set
``HUB_MDNS_ENABLED=0`` to disable this in-container advertiser.
"""
import logging
import os
import socket

logger = logging.getLogger(__name__)

SERVICE_TYPE = "_conecsa._tcp.local."

_zeroconf = None
_service_info = None


def _local_ip() -> str:
    """Best-effort primary LAN IPv4 of this host."""
    advertised = os.environ.get("DEVICE_ADVERTISE_IP")
    if advertised:
        return advertised
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        logger.warning("Unable to determine a non-loopback IPv4 address; set DEVICE_ADVERTISE_IP to override")
        return ""


def start_advertising() -> None:
    """Register the mDNS service. Idempotent; safe to call once at startup."""
    global _zeroconf, _service_info

    if os.environ.get("HUB_MDNS_ENABLED", "1") not in ("1", "true", "True"):
        logger.info("mDNS advertising disabled (HUB_MDNS_ENABLED)")
        return
    if _zeroconf is not None:
        return

    # Imported lazily so a missing/old zeroconf never blocks gateway startup.
    from zeroconf import ServiceInfo, Zeroconf

    hostname = socket.gethostname()
    # Use the same persisted device id as enrollment so the hub's paired-set and
    # the device's certificate SAN line up with what it discovers over mDNS.
    try:
        from .enroll import device_id as _device_id
        device_id = _device_id()
    except Exception:  # noqa: BLE001
        device_id = os.environ.get("DEVICE_ID", hostname)
    name = os.environ.get("DEVICE_NAME", hostname)
    http_port = int(os.environ.get("DEVICE_HTTP_PORT", "80"))
    gateway_port = int(os.environ.get("GATEWAY_PORT", "5000"))
    version = os.environ.get("DEVICE_VERSION", "")
    ip = _local_ip()
    if not ip or ip.startswith("127."):
        logger.warning("Refusing to advertise loopback/empty address (%s). Set DEVICE_ADVERTISE_IP to override.", ip)
        return
    # Advertise enrollment state so the hub can hint "needs pairing" without
    # probing (best-effort; the hub also reads /enroll/info authoritatively).
    try:
        from .enroll import is_enrolled
        enrolled = "1" if is_enrolled() else "0"
    except Exception:  # noqa: BLE001
        enrolled = "0"
    instance = f"{name}.{SERVICE_TYPE}"
    properties = {
        "device_id": device_id,
        "name": name,
        "http_port": str(http_port),
        "gateway_port": str(gateway_port),
        "version": version,
        "enrolled": enrolled,
    }
    info = ServiceInfo(
        SERVICE_TYPE,
        instance,
        addresses=[socket.inet_aton(ip)],
        port=gateway_port,
        properties=properties,
        server=f"{hostname}.local.",
    )

    zc = Zeroconf()
    zc.register_service(info)
    _zeroconf = zc
    _service_info = info
    logger.info(
        "mDNS advertising %s at %s (gateway:%s, http:%s)",
        instance, ip, gateway_port, http_port,
    )


def stop_advertising() -> None:
    """Unregister the service and close the Zeroconf instance."""
    global _zeroconf, _service_info
    if _zeroconf is None:
        return
    try:
        if _service_info is not None:
            _zeroconf.unregister_service(_service_info)
    except Exception as ex:  # noqa: BLE001 - shutdown best-effort
        logger.warning("Failed to unregister mDNS service: %s", ex)
    finally:
        _zeroconf.close()
        _zeroconf = None
        _service_info = None
