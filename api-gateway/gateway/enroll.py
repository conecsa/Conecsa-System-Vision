"""Device enrollment: the conecsa-hub-vision hub is the certificate authority,
and this endpoint lets a fresh device obtain a hub-signed server certificate
without its private key ever leaving the device.

A device generates an EC P-256 keypair on first boot and persists it under
``CONECSA_CERT_DIR`` (a writable volume). Pairing is operator-initiated from the
hub:

  1. ``GET  /enroll/info``     → device id, public-key fingerprint, state and
                                 whether a pairing token is required.
  2. ``POST /enroll/csr``      → returns a CSR whose SAN is the logical identity
                                 ``device-<id>.conecsa.local``.
  3. ``POST /enroll/complete`` → ``{device_cert, ca_cert}`` → installs the
                                 hub-signed server cert and the hub CA (used by
                                 nginx to require the hub's client cert / mTLS).

By default pairing needs no secret: while the device is unenrolled, the first hub
on the (trusted) LAN to pair wins, so the operator just clicks "Pair" in the hub.
Once enrolled, mTLS locks the device to that hub. For stricter deployments set
``DEVICE_PAIR_TOKEN`` to require a shared pairing secret on every enroll request.
"""
import hashlib
import hmac
import logging
import os
from typing import TYPE_CHECKING

from flask import Blueprint, jsonify, request

from .helpers import _hub_verified

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric import ec

logger = logging.getLogger(__name__)

CERT_DIR = os.environ.get("CONECSA_CERT_DIR", "/etc/conecsa/certs")
KEY_PATH = os.path.join(CERT_DIR, "device.key")
CERT_PATH = os.path.join(CERT_DIR, "device.crt")
CA_PATH = os.path.join(CERT_DIR, "ca.crt")
# The host's hostname, bind-mounted from the host (see docker-compose). It is the
# same value the host avahi-daemon uses as the mDNS instance name, so the hub
# discovers the device under the same id the cert SAN and paired-set use.
HOST_HOSTNAME_PATH = os.environ.get("CONECSA_HOST_HOSTNAME", "/etc/conecsa/host_hostname")

enroll_bp = Blueprint("enroll", __name__, url_prefix="/enroll")


def device_id() -> str:
    """Stable device identifier shared by enrollment, the certificate SAN and the
    mDNS advertisement, so the hub sees one consistent id.

    Priority: ``DEVICE_ID`` env → the host hostname (which equals the avahi mDNS
    instance name) → this container's hostname (dev fallback).
    """
    import socket

    env = os.environ.get("DEVICE_ID", "").strip()
    if env:
        return env
    try:
        with open(HOST_HOSTNAME_PATH, "r", encoding="utf-8") as fh:
            host = fh.read().strip()
            if host:
                return host
    except OSError:
        logger.debug(
            "Could not read host hostname from %s; falling back to container hostname",
            HOST_HOSTNAME_PATH,
            exc_info=True,
        )
    return socket.gethostname()


def logical_name() -> str:
    """The IP-independent identity placed in the certificate SAN."""
    return f"device-{device_id()}.conecsa.local"


def is_enrolled() -> bool:
    """True once a hub-signed server cert and the hub CA are installed."""
    return os.path.exists(CERT_PATH) and os.path.exists(CA_PATH)


def _ensure_dir() -> None:
    os.makedirs(CERT_DIR, exist_ok=True)


def _load_or_create_key() -> "ec.EllipticCurvePrivateKey":
    """Load the device private key, generating it on first use."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    _ensure_dir()
    if os.path.exists(KEY_PATH):
        with open(KEY_PATH, "rb") as fh:
            key = serialization.load_pem_private_key(fh.read(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise TypeError(f"{KEY_PATH} is not an EC private key; delete it to regenerate")
        return key

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # Restrictive permissions: the private key must never leave the device.
    fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
    logger.info("generated device enrollment key at %s", KEY_PATH)
    return key


def public_fingerprint() -> str:
    """SHA-256 (hex) of the device public key — shown to the operator for a TOFU
    confirmation against the device logs."""
    from cryptography.hazmat.primitives import serialization

    key = _load_or_create_key()
    der = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(der).hexdigest()


def _build_csr() -> bytes:
    """Generate a CSR for the device's logical identity (PEM bytes)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.x509.oid import NameOID

    key = _load_or_create_key()
    name = logical_name()
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return csr.public_bytes(serialization.Encoding.PEM)


def _configured_token():
    """The optional pairing token (``DEVICE_PAIR_TOKEN``), or ``None`` if unset.

    When unset, the device pairs without a token (trusted-LAN, first-enrollment
    wins) so the operator just clicks "Pair" in the hub — no secret to copy.
    Set it only for stricter deployments where a shared pairing secret is wanted.
    """
    token = os.environ.get("DEVICE_PAIR_TOKEN", "").strip()
    return token or None


def token_required() -> bool:
    """Whether the hub must supply a pairing token for this device."""
    return _configured_token() is not None


def _pairing_allowed():
    """Authorize a pairing request. Returns ``(ok, message)``.

    - If a token is configured, it must match (constant-time).
    - Otherwise pairing is allowed only while the device is not yet enrolled;
      re-pairing an enrolled device requires the token or the existing mTLS
      channel (so a rogue hub cannot hijack a paired device over plain HTTP).
    """
    token = _configured_token()
    if token is not None:
        provided = str((request.get_json(silent=True) or {}).get("token", ""))
        if hmac.compare_digest(provided, token):
            return True, ""
        return False, "invalid pairing token"
    if is_enrolled():
        return False, "device already enrolled; reset it to pair with a new hub"
    return True, ""


def _install_certs(device_cert: str, ca_cert: str) -> None:
    """Persist the hub-signed server cert and the hub CA atomically."""
    _ensure_dir()
    for path, data in ((CERT_PATH, device_cert), (CA_PATH, ca_cert)):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)


@enroll_bp.route("/info", methods=["GET"])
def info():
    """Public pairing info — no secrets; safe to call unauthenticated."""
    try:
        fingerprint = public_fingerprint()
    except Exception as ex:  # noqa: BLE001
        logger.error("failed to compute key fingerprint: %s", ex)
        return jsonify({"error": "failed to compute key fingerprint"}), 500
    return jsonify({
        "device_id": device_id(),
        "logical_name": logical_name(),
        "enrolled": is_enrolled(),
        "token_required": token_required(),
        "key_fingerprint": fingerprint,
    })


@enroll_bp.route("/csr", methods=["POST"])
def csr():
    """Return a CSR for the hub to sign (authorized per the pairing policy)."""
    ok, msg = _pairing_allowed()
    if not ok:
        return jsonify({"error": msg}), 403
    try:
        pem = _build_csr().decode("ascii")
    except Exception as ex:  # noqa: BLE001
        logger.error("failed to build CSR: %s", ex)
        return jsonify({"error": "failed to build CSR"}), 500
    return jsonify({"csr": pem, "logical_name": logical_name()})


@enroll_bp.route("/complete", methods=["POST"])
def complete():
    """Install the hub-signed certificate and CA (requires the pairing token).

    nginx is reloaded automatically by its entrypoint watcher when the cert
    files appear, flipping the device into mTLS-enforcing mode.
    """
    ok, msg = _pairing_allowed()
    if not ok:
        return jsonify({"error": msg}), 403
    body = request.get_json(silent=True) or {}
    device_cert = body.get("device_cert")
    ca_cert = body.get("ca_cert")
    if not device_cert or not ca_cert:
        return jsonify({"error": "device_cert and ca_cert are required"}), 400
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization

        key = _load_or_create_key()
        cert = x509.load_pem_x509_certificate(device_cert.encode("utf-8"))
        ca = x509.load_pem_x509_certificate(ca_cert.encode("utf-8"))
        _ = ca.subject  # ensure CA cert parses

        sans = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if logical_name() not in sans.get_values_for_type(x509.DNSName):
            return jsonify({"error": "device certificate SAN does not match this device"}), 400

        def spki(k) -> bytes:
            return k.public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )

        if spki(cert.public_key()) != spki(key.public_key()):
            return jsonify({"error": "device certificate does not match device key"}), 400

        _install_certs(device_cert, ca_cert)
    except Exception as ex:  # noqa: BLE001
        logger.error("failed to validate/install certificates: %s", ex)
        return jsonify({"error": "failed to install certificates"}), 500
    logger.info("device enrolled: installed hub-signed certificate and CA")
    return jsonify({
        "status": "enrolled",
        "device_id": device_id(),
        "logical_name": logical_name(),
    })


def _reset_authorized() -> bool:
    """Unpair must come from the owning hub: either over mTLS (nginx sets
    X-Conecsa-Client-Verify=SUCCESS for a CA-signed client cert, and
    _hub_verified additionally requires the request to come from the
    terminator itself so the header cannot be spoofed by another container)
    or with the configured pairing token."""
    token = _configured_token()
    if token is not None:
        provided = str((request.get_json(silent=True) or {}).get("token", ""))
        if hmac.compare_digest(provided, token):
            return True
    return _hub_verified()


@enroll_bp.route("/reset", methods=["POST"])
def reset():
    """Unpair: clear the hub-signed cert + CA so the device returns to enrollment
    mode (nginx flips back automatically). Authorized via mTLS or the token."""
    if not is_enrolled():
        return jsonify({"status": "not_enrolled"})
    if not _reset_authorized():
        return jsonify({"error": "unpair requires the owning hub (mTLS) or the pairing token"}), 403
    for path in (CERT_PATH, CA_PATH):
        try:
            os.remove(path)
        except FileNotFoundError:
            # Reset is idempotent; the file may already be absent.
            pass
    logger.info("device unpaired: cleared hub-signed certificate and CA")
    return jsonify({"status": "reset", "logical_name": logical_name()})
