"""Unit tests for the InterfaceConfig -> JSON mapper."""
from types import SimpleNamespace

from gateway.hardware import _iface_to_dict


def _iface(**kw):
    base = dict(
        name="eth0",
        method="static",
        address="192.168.1.10",
        prefix="24",
        gateway="192.168.1.1",
        dns=["1.1.1.1", "8.8.8.8"],
        present=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


class TestIfaceToDict:
    def test_full_config(self):
        assert _iface_to_dict(_iface()) == {
            "name": "eth0",
            "method": "static",
            "address": "192.168.1.10",
            "prefix": "24",
            "gateway": "192.168.1.1",
            "dns": ["1.1.1.1", "8.8.8.8"],
            "present": True,
        }

    def test_empty_method_defaults_to_auto(self):
        assert _iface_to_dict(_iface(method=""))["method"] == "auto"

    def test_empty_strings_become_none(self):
        d = _iface_to_dict(_iface(address="", prefix="", gateway=""))
        assert d["address"] is None
        assert d["prefix"] is None
        assert d["gateway"] is None

    def test_dns_is_materialized_list(self):
        d = _iface_to_dict(_iface(dns=iter(["9.9.9.9"])))
        assert d["dns"] == ["9.9.9.9"]

    def test_absent_interface(self):
        assert _iface_to_dict(_iface(present=False))["present"] is False
