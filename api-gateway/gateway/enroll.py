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
  3. ``POST /enroll/complete`` → ``{device_cert, ca_cert, hub_time}`` → adopts
                                 the hub's clock (see gateway/clock.py) and
                                 installs the hub-signed server cert and the hub
                                 CA (used by nginx to require mTLS).

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

from . import clock
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
    """Load the device private key, generating it exactly once on first use.

    Concurrency-safe by construction: waitress serves requests on many
    threads, and the hub calls /enroll/info and /enroll/csr back to back, so
    two first requests race here. The key is staged fully (written + fsynced)
    under a unique temp name and then hard-linked into place — os.link fails
    atomically when another request already won, and KEY_PATH can never be
    observed half-written (an O_EXCL write directly to KEY_PATH could: the
    loser would load the winner's file mid-write). Whoever loses the race
    loads the winner's key instead.
    """
    import secrets

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    def _load() -> "ec.EllipticCurvePrivateKey":
        with open(KEY_PATH, "rb") as fh:
            key = serialization.load_pem_private_key(fh.read(), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise TypeError(f"{KEY_PATH} is not an EC private key; delete it to regenerate")
        return key

    _ensure_dir()
    if os.path.exists(KEY_PATH):
        return _load()

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    # Restrictive permissions: the private key must never leave the device.
    staged = f"{KEY_PATH}.tmp-{secrets.token_hex(8)}"
    fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(pem)
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(staged, KEY_PATH)
    except FileExistsError:
        # A concurrent request published its key first — that one is the truth.
        return _load()
    finally:
        os.unlink(staged)
    _fsync_dir(CERT_DIR)
    logger.info("generated device enrollment key at %s", KEY_PATH)
    return key


def _fsync_dir(directory: str) -> None:
    """Make a directory entry durable (best-effort)."""
    try:
        dir_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


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
    """Persist the hub-signed server cert and the hub CA (near-atomic pair).

    Both temp files are written and fsynced before either rename, so the
    window where nginx could observe a new leaf with the old CA shrinks to
    the two back-to-back renames (microseconds; nginx only re-reads on its
    entrypoint-triggered reload). Accepted residual — a full versioned-dir
    switch is not worth the moving parts here.
    """
    _ensure_dir()
    staged = []
    for path, data in ((CERT_PATH, device_cert), (CA_PATH, ca_cert)):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        staged.append((tmp, path))
    for tmp, path in staged:
        os.replace(tmp, path)
    _fsync_dir(CERT_DIR)


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

        # The supplied CA must actually be a CA, and it must be the direct
        # issuer of the leaf — otherwise any parsable certificate pair could
        # flip nginx into "enforcing" mode against a CA that never signed
        # anything, silently bricking the mTLS channel.
        try:
            basic = ca.extensions.get_extension_for_class(x509.BasicConstraints).value
        except x509.ExtensionNotFound:
            return jsonify({"error": "CA certificate has no BasicConstraints"}), 400
        if not basic.ca:
            return jsonify({"error": "supplied CA certificate is not a CA"}), 400
        try:
            key_usage = ca.extensions.get_extension_for_class(x509.KeyUsage).value
            if not key_usage.key_cert_sign:
                return jsonify({"error": "CA certificate cannot sign certificates"}), 400
        except x509.ExtensionNotFound:
            pass  # KeyUsage is optional; BasicConstraints already gates
        try:
            cert.verify_directly_issued_by(ca)
        except Exception:  # noqa: BLE001 - one answer for every mismatch
            return jsonify({"error": "device certificate was not issued by the supplied CA"}), 400
        try:
            eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            if x509.oid.ExtendedKeyUsageOID.SERVER_AUTH not in eku:
                return jsonify({"error": "device certificate lacks the serverAuth usage"}), 400
        except x509.ExtensionNotFound:
            pass  # no EKU restricts nothing

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

        # Adopt the hub's clock BEFORE the certificates land: installing them
        # flips nginx into mTLS-enforcing mode, and from that moment the device
        # validates the hub's client certificate. With a dead RTC and no NTP the
        # local clock can predate the CA's not_before, which would reject every
        # hub call as "certificate is not yet valid" — pairing would appear to
        # succeed and the device would go offline for good. This is also the
        # only channel that works while the clock is wrong (no validation here).
        # A refused step is fatal for the same reason: enrolling with a wrong
        # clock strands the device, so install nothing and let the hub retry.
        # Two cases are let through with a warning instead, because retrying
        # cannot fix them: a hub too old to send hub_time at all, and a host
        # with no hardware agent to set the clock (the dev stack runs the
        # gateway without the Jetson-only `os` agent; on a device the agent is
        # always up, and the persisted clock floor covers a flashed unit).
        hub_time = body.get("hub_time")
        if hub_time is None:
            logger.warning("pairing without hub_time (old hub?); "
                           "clock not synchronized")
        else:
            outcome = clock.step_clock(hub_time, "pairing", force=True)
            if outcome is clock.StepOutcome.UNREACHABLE:
                logger.warning("pairing without clock sync: no hardware agent "
                               "reachable (development host?)")
            elif outcome is not clock.StepOutcome.APPLIED:
                logger.error("pairing aborted: could not adopt the hub's clock (%s)",
                             outcome.value)
                return jsonify({"error": "could not synchronize the device clock; "
                                         "nothing was installed — retry pairing"}), 500

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
