import json
import subprocess

from softether_wrapper import network


class _FakeCompleted:
    def __init__(self, returncode, stdout=b""):
        self.returncode = returncode
        self.stdout = stdout


def test_tap_addresses_parses_ip_json(monkeypatch):
    monkeypatch.setattr(network, "_ip_command", lambda: ["ip"])
    payload = [
        {
            "ifname": "vpn_vpn0",
            "operstate": "UP",
            "addr_info": [
                {"family": "inet", "local": "10.0.0.10", "prefixlen": 8},
                {"family": "inet6", "local": "fe80::1", "prefixlen": 64},
            ],
        }
    ]

    def fake_run(*args, **kwargs):
        return _FakeCompleted(0, json.dumps(payload).encode())

    monkeypatch.setattr(network.subprocess, "run", fake_run)
    assert network.tap_addresses("vpn_vpn0") == ["10.0.0.10/8", "fe80::1/64"]


def test_tap_addresses_handles_missing_ip(monkeypatch):
    monkeypatch.setattr(network, "_ip_command", lambda: [])
    assert network.tap_addresses("vpn_vpn0") == []


def test_tap_addresses_handles_failure(monkeypatch):
    monkeypatch.setattr(network, "_ip_command", lambda: ["ip"])
    monkeypatch.setattr(
        network.subprocess, "run", lambda *a, **k: _FakeCompleted(1, b"")
    )
    assert network.tap_addresses("vpn_vpn0") == []


def test_tap_is_up(monkeypatch):
    monkeypatch.setattr(network, "_ip_command", lambda: ["ip"])
    monkeypatch.setattr(
        network.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(0, b'[{"ifname": "vpn_vpn0", "operstate": "UP"}]'),
    )
    assert network.tap_is_up("vpn_vpn0")
    monkeypatch.setattr(
        network.subprocess,
        "run",
        lambda *a, **k: _FakeCompleted(0, b'[{"ifname": "vpn_vpn0", "operstate": "DOWN"}]'),
    )
    assert not network.tap_is_up("vpn_vpn0")


def test_timeout_is_handled(monkeypatch):
    monkeypatch.setattr(network, "_ip_command", lambda: ["ip"])

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="ip", timeout=3)

    monkeypatch.setattr(network.subprocess, "run", boom)
    assert network.tap_addresses("vpn_vpn0") == []
