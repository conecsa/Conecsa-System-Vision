"""Unit tests for device enrollment identity + crypto helpers."""
import os
from datetime import datetime, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from gateway import enroll


@pytest.fixture
def cert_dir(tmp_path, monkeypatch):
    """Point the module's cert paths at a temp dir for isolated key generation."""
    d = tmp_path / "certs"
    monkeypatch.setattr(enroll, "CERT_DIR", str(d))
    monkeypatch.setattr(enroll, "KEY_PATH", str(d / "device.key"))
    monkeypatch.setattr(enroll, "CERT_PATH", str(d / "device.crt"))
    monkeypatch.setattr(enroll, "CA_PATH", str(d / "ca.crt"))
    return d


class TestDeviceId:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv("DEVICE_ID", "cam-42")
        assert enroll.device_id() == "cam-42"

    def test_reads_host_hostname_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEVICE_ID", raising=False)
        hostfile = tmp_path / "host_hostname"
        hostfile.write_text("jetson-01\n")
        monkeypatch.setattr(enroll, "HOST_HOSTNAME_PATH", str(hostfile))
        assert enroll.device_id() == "jetson-01"

    def test_falls_back_to_container_hostname(self, monkeypatch):
        monkeypatch.delenv("DEVICE_ID", raising=False)
        monkeypatch.setattr(enroll, "HOST_HOSTNAME_PATH", "/nonexistent/path")
        # Falls back to socket.gethostname() — just assert it's a non-empty string.
        assert isinstance(enroll.device_id(), str)
        assert enroll.device_id() != ""


class TestLogicalName:
    def test_format(self, monkeypatch):
        monkeypatch.setenv("DEVICE_ID", "cam-42")
        assert enroll.logical_name() == "device-cam-42.conecsa.local"


class TestIsEnrolled:
    def test_false_when_certs_absent(self, cert_dir):
        assert enroll.is_enrolled() is False

    def test_true_when_both_present(self, cert_dir):
        cert_dir.mkdir(parents=True, exist_ok=True)
        (cert_dir / "device.crt").write_text("x")
        (cert_dir / "ca.crt").write_text("x")
        assert enroll.is_enrolled() is True


class TestPublicFingerprint:
    def test_generates_key_and_stable_hex(self, cert_dir):
        fp1 = enroll.public_fingerprint()
        assert len(fp1) == 64  # SHA-256 hex
        assert all(c in "0123456789abcdef" for c in fp1)
        # Key is persisted with 0600 perms, and the fingerprint is stable.
        assert os.path.exists(str(cert_dir / "device.key"))
        assert oct(os.stat(str(cert_dir / "device.key")).st_mode & 0o777) == "0o600"
        assert enroll.public_fingerprint() == fp1


class TestBuildCsr:
    def test_csr_has_logical_common_name(self, cert_dir, monkeypatch):
        monkeypatch.setenv("DEVICE_ID", "cam-42")
        pem = enroll._build_csr()
        csr = x509.load_pem_x509_csr(pem)
        cn = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        assert cn == "device-cam-42.conecsa.local"
        san = csr.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        assert san.value.get_values_for_type(x509.DNSName) == [
            "device-cam-42.conecsa.local"
        ]

    def test_csr_signature_is_valid(self, cert_dir):
        csr = x509.load_pem_x509_csr(enroll._build_csr())
        assert csr.is_signature_valid


class TestTokenRequired:
    def test_no_token_by_default(self, monkeypatch):
        monkeypatch.delenv("DEVICE_PAIR_TOKEN", raising=False)
        assert enroll.token_required() is False

    def test_token_required_when_set(self, monkeypatch):
        monkeypatch.setenv("DEVICE_PAIR_TOKEN", "secret")
        assert enroll.token_required() is True


class TestCompleteAdoptsTheHubClock:
    """Pairing is the one channel that works while the device clock is wrong
    (nothing is validated on it), so `/enroll/complete` must take the hub's time
    BEFORE the certificates land — installing them flips nginx into enforcing
    mode, and from then on a clock older than the CA's not_before rejects every
    hub call."""

    @pytest.fixture
    def client(self, cert_dir, monkeypatch):
        from flask import Flask
        monkeypatch.setenv("DEVICE_ID", "cam-42")
        monkeypatch.delenv("DEVICE_PAIR_TOKEN", raising=False)
        app = Flask(__name__)
        app.register_blueprint(enroll.enroll_bp)
        return app.test_client()

    @staticmethod
    def _hub_signed_cert() -> tuple:
        """(device_cert, ca_cert) PEMs for the device's own CSR, as the hub sends."""
        csr = x509.load_pem_x509_csr(enroll._build_csr())
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-hub")])
        span = {
            "not_valid_before": datetime(2020, 1, 1, tzinfo=timezone.utc),
            "not_valid_after": datetime(2050, 1, 1, tzinfo=timezone.utc),
        }
        ca_cert = (
            x509.CertificateBuilder()
            .subject_name(ca_name).issuer_name(ca_name)
            .public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(span["not_valid_before"])
            .not_valid_after(span["not_valid_after"])
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256())
        )
        leaf = (
            x509.CertificateBuilder()
            .subject_name(csr.subject).issuer_name(ca_name)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(span["not_valid_before"])
            .not_valid_after(span["not_valid_after"])
            .add_extension(
                csr.extensions.get_extension_for_class(x509.SubjectAlternativeName).value,
                critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        pem = serialization.Encoding.PEM
        return (leaf.public_bytes(pem).decode(), ca_cert.public_bytes(pem).decode())

    def _post(self, client, monkeypatch, outcome=enroll.clock.StepOutcome.APPLIED):
        """Run a full pairing, recording the order of the two side effects."""
        device_cert, ca_cert = self._hub_signed_cert()
        order = []

        def fake_step(raw, source, force=False):
            order.append(("clock", raw, source, force))
            return outcome

        real_install = enroll._install_certs
        monkeypatch.setattr(enroll.clock, "step_clock", fake_step)
        monkeypatch.setattr(enroll, "_install_certs",
                            lambda c, a: (order.append(("install",)), real_install(c, a)))
        resp = client.post("/enroll/complete", json={
            "device_cert": device_cert,
            "ca_cert": ca_cert,
            "hub_time": "2026-08-03T10:00:00.000Z",
        })
        return resp, order

    def test_clock_is_set_before_the_certificates_are_installed(
            self, client, monkeypatch):
        resp, order = self._post(client, monkeypatch)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "enrolled"
        assert [step[0] for step in order] == ["clock", "install"]
        # Forced: the bootstrap step bypasses the poll-path threshold and rate
        # limit, so pairing always leaves a clock floor behind.
        assert order[0][1:] == ("2026-08-03T10:00:00.000Z", "pairing", True)
        assert enroll.is_enrolled() is True

    @pytest.mark.parametrize("outcome", [enroll.clock.StepOutcome.REJECTED,
                                         enroll.clock.StepOutcome.SKIPPED])
    def test_a_refused_clock_step_aborts_the_pairing(self, client, monkeypatch, outcome):
        # Enrolling with a wrong clock strands the device (every later hub
        # call fails "certificate is not yet valid"), so a rejected time step
        # must install nothing and let the hub retry — the exact failure mode
        # gateway/clock.py's docstring calls fatal.
        resp, order = self._post(client, monkeypatch, outcome=outcome)
        assert resp.status_code == 500
        assert [step[0] for step in order] == ["clock"], "no install on failure"
        assert enroll.is_enrolled() is False

    def test_an_unreachable_hardware_agent_does_not_block_pairing(
            self, client, monkeypatch):
        # A development host runs the gateway without the Jetson-only `os`
        # agent, so there is nothing to set the clock with — and nothing a
        # retry could change. Pair anyway (logged), unlike a refused step.
        resp, order = self._post(client, monkeypatch,
                                 outcome=enroll.clock.StepOutcome.UNREACHABLE)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "enrolled"
        assert [step[0] for step in order] == ["clock", "install"]
        assert enroll.is_enrolled() is True

    def test_an_older_hub_omitting_hub_time_still_pairs(self, client, monkeypatch):
        # A hub too old to send hub_time cannot be asked to retry with data it
        # does not have: skip the sync (logged) instead of failing the pairing.
        device_cert, ca_cert = self._hub_signed_cert()
        seen = []
        monkeypatch.setattr(enroll.clock, "step_clock",
                            lambda raw, source, force=False: seen.append(raw))
        resp = client.post("/enroll/complete", json={
            "device_cert": device_cert, "ca_cert": ca_cert})
        assert resp.status_code == 200
        assert seen == [], "no sync attempt without hub_time"


class TestResetAuthorized:
    """Unpair authorization must not be spoofable: the mTLS header only counts
    when the request was relayed by the nginx terminator itself."""

    TERMINATOR_IP = "10.66.0.9"

    def _ctx(self, remote_addr, headers=None):
        from flask import Flask
        return Flask(__name__).test_request_context(
            "/enroll/reset", method="POST", headers=headers or {},
            environ_base={"REMOTE_ADDR": remote_addr})

    @pytest.fixture(autouse=True)
    def _pin_terminator(self, monkeypatch):
        from gateway import helpers
        monkeypatch.delenv("DEVICE_PAIR_TOKEN", raising=False)
        monkeypatch.setattr(helpers, "_resolve_proxy_ips",
                            lambda: frozenset({self.TERMINATOR_IP}))
        monkeypatch.setattr(helpers, "_proxy_cache",
                            {"ips": frozenset(), "at": float("-inf")})

    def test_header_via_the_terminator_authorizes(self):
        with self._ctx(self.TERMINATOR_IP,
                       {"X-Conecsa-Client-Verify": "SUCCESS"}):
            assert enroll._reset_authorized() is True

    def test_spoofed_header_from_another_container_is_rejected(self):
        with self._ctx("172.20.0.5", {"X-Conecsa-Client-Verify": "SUCCESS"}):
            assert enroll._reset_authorized() is False

    def test_pairing_token_still_authorizes_without_mtls(self, monkeypatch):
        monkeypatch.setenv("DEVICE_PAIR_TOKEN", "secret")
        from flask import Flask
        with Flask(__name__).test_request_context(
                "/enroll/reset", method="POST", json={"token": "secret"},
                environ_base={"REMOTE_ADDR": "172.20.0.5"}):
            assert enroll._reset_authorized() is True


class TestKeyCreationRace:
    def test_concurrent_first_requests_share_one_key(self, cert_dir,
                                                     monkeypatch):
        # Waitress is thread-per-connection and the hub calls /enroll/info and
        # /enroll/csr back to back: two first requests must converge on ONE
        # key, or a CSR issued from the loser no longer matches the stored key.
        # Several rounds because the interesting interleavings (including the
        # loser loading while the winner is still writing, which CI caught
        # against an earlier O_EXCL-only fix) are timing-dependent.
        import os as _os
        import threading

        for round_no in range(10):
            monkeypatch.setattr(
                enroll, "KEY_PATH", str(cert_dir / f"device-{round_no}.key"))
            barrier = threading.Barrier(2)
            keys = []

            def create(barrier=barrier, keys=keys):
                barrier.wait()
                keys.append(enroll._load_or_create_key())

            threads = [threading.Thread(target=create) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)

            assert len(keys) == 2, f"round {round_no}: a racer crashed"
            nums = {k.private_numbers().private_value for k in keys}
            assert len(nums) == 1, "both requests must hold the same key"
            # The key on disk is that same one, and no staging litter remains.
            assert enroll._load_or_create_key().private_numbers() \
                .private_value in nums
            litter = [f for f in _os.listdir(cert_dir) if ".tmp-" in f]
            assert litter == []

    def test_an_existing_key_is_never_truncated(self, cert_dir):
        first = enroll._load_or_create_key()
        again = enroll._load_or_create_key()
        assert first.private_numbers().private_value == \
            again.private_numbers().private_value

    def test_the_key_file_is_private(self, cert_dir):
        import os as _os
        enroll._load_or_create_key()
        mode = _os.stat(cert_dir / "device.key").st_mode & 0o777
        assert mode == 0o600


class TestCompleteValidatesTheChain:
    """A parsable certificate pair is not enough: installing a CA that never
    signed the leaf flips nginx into enforcing mode against a dead channel."""

    @pytest.fixture
    def client(self, cert_dir, monkeypatch):
        from flask import Flask
        monkeypatch.setenv("DEVICE_ID", "cam-42")
        monkeypatch.delenv("DEVICE_PAIR_TOKEN", raising=False)
        monkeypatch.setattr(enroll.clock, "step_clock",
                            lambda raw, source, force=False: enroll.clock.StepOutcome.APPLIED)
        app = Flask(__name__)
        app.register_blueprint(enroll.enroll_bp)
        return app.test_client()

    @staticmethod
    def _make_ca(ca=True, key_cert_sign=True):
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-hub")])
        builder = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2020, 1, 1, tzinfo=timezone.utc))
            .not_valid_after(datetime(2050, 1, 1, tzinfo=timezone.utc))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None),
                           critical=True)
        )
        if not key_cert_sign:
            builder = builder.add_extension(
                x509.KeyUsage(digital_signature=True, content_commitment=False,
                              key_encipherment=False, data_encipherment=False,
                              key_agreement=False, key_cert_sign=False,
                              crl_sign=False, encipher_only=False,
                              decipher_only=False),
                critical=True)
        return key, builder.sign(key, hashes.SHA256()), name

    @classmethod
    def _make_leaf(cls, ca_key, ca_name, eku=None):
        csr = x509.load_pem_x509_csr(enroll._build_csr())
        builder = (
            x509.CertificateBuilder()
            .subject_name(csr.subject).issuer_name(ca_name)
            .public_key(csr.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2020, 1, 1, tzinfo=timezone.utc))
            .not_valid_after(datetime(2050, 1, 1, tzinfo=timezone.utc))
            .add_extension(
                csr.extensions.get_extension_for_class(
                    x509.SubjectAlternativeName).value, critical=False)
        )
        if eku is not None:
            builder = builder.add_extension(x509.ExtendedKeyUsage(eku),
                                            critical=False)
        return builder.sign(ca_key, hashes.SHA256())

    @staticmethod
    def _pem(cert):
        return cert.public_bytes(serialization.Encoding.PEM).decode()

    def _complete(self, client, leaf, ca):
        return client.post("/enroll/complete", json={
            "device_cert": self._pem(leaf), "ca_cert": self._pem(ca),
            "hub_time": "2026-08-03T10:00:00.000Z"})

    def test_a_non_ca_certificate_is_rejected(self, client):
        ca_key, _, ca_name = self._make_ca()
        _, non_ca, _ = self._make_ca(ca=False)
        leaf = self._make_leaf(ca_key, ca_name)
        resp = self._complete(client, leaf, non_ca)
        assert resp.status_code == 400
        assert "not a CA" in resp.get_json()["error"]
        assert enroll.is_enrolled() is False

    def test_a_ca_that_did_not_sign_the_leaf_is_rejected(self, client):
        ca_key, _, ca_name = self._make_ca()
        _, other_ca, _ = self._make_ca()
        leaf = self._make_leaf(ca_key, ca_name)
        resp = self._complete(client, leaf, other_ca)
        assert resp.status_code == 400
        assert "not issued by" in resp.get_json()["error"]
        assert enroll.is_enrolled() is False

    def test_a_ca_that_cannot_sign_certs_is_rejected(self, client):
        ca_key, ca_cert, ca_name = self._make_ca(key_cert_sign=False)
        leaf = self._make_leaf(ca_key, ca_name)
        resp = self._complete(client, leaf, ca_cert)
        assert resp.status_code == 400
        assert "cannot sign" in resp.get_json()["error"]

    def test_an_eku_without_server_auth_is_rejected(self, client):
        from cryptography.x509.oid import ExtendedKeyUsageOID
        ca_key, ca_cert, ca_name = self._make_ca()
        leaf = self._make_leaf(ca_key, ca_name,
                               eku=[ExtendedKeyUsageOID.CLIENT_AUTH])
        resp = self._complete(client, leaf, ca_cert)
        assert resp.status_code == 400
        assert "serverAuth" in resp.get_json()["error"]

    def test_a_correct_chain_enrolls(self, client):
        from cryptography.x509.oid import ExtendedKeyUsageOID
        ca_key, ca_cert, ca_name = self._make_ca()
        leaf = self._make_leaf(ca_key, ca_name,
                               eku=[ExtendedKeyUsageOID.SERVER_AUTH])
        resp = self._complete(client, leaf, ca_cert)
        assert resp.status_code == 200
        assert enroll.is_enrolled() is True
