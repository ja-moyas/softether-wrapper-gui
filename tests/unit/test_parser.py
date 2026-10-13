from pathlib import Path

import pytest

from softether_wrapper import vpncmd_parser as parser
from softether_wrapper.models import ConnectionState

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_about_version():
    assert parser.parse_about(load("about.txt")) == "Version 5.01 Build 9674"


def test_versionget():
    info = parser.parse_version(load("versionget.txt"))
    assert info.product == "SoftEther VPN Client Developer Edition"
    assert info.version.startswith("Version 5.01")
    assert info.os_type == "Linux"


def test_account_list_groups_records():
    accounts = parser.parse_account_list(load("accountlist_multi.txt"))
    assert [a.name for a in accounts] == ["MyVPN", "BackupVPN"]
    assert accounts[0].server == "vpn.example.com:443"
    assert accounts[0].state is ConnectionState.CONNECTED
    assert accounts[1].state is ConnectionState.DISCONNECTED
    assert accounts[1].hub == "BackupHub"


def test_account_get():
    detail = parser.parse_account_get(load("accountget.txt"))
    assert detail.name == "MyVPN"
    assert detail.server_host == "vpn.example.com"
    assert detail.server_port == "443"
    assert detail.server == "vpn.example.com:443"
    assert detail.username == "alice"
    assert detail.encrypt == "Enable"
    assert detail.raw["Data Compression"] == "Disable"


def test_account_status_connected():
    status = parser.parse_account_status(load("accountstatus_connected.txt"))
    assert status.is_connected
    assert not status.is_connecting
    assert status.tcp_connections_count == 2
    assert status.has_live_transport
    assert not status.is_phantom
    assert status.outgoing_bytes == 1703088
    assert status.incoming_bytes == 14414551
    assert status.outgoing_packets == 10814
    assert status.encryption.startswith("Enabled")


def test_account_status_phantom():
    """Connected in name only: the session object survives with no transport."""
    status = parser.parse_account_status(load("accountstatus_phantom.txt"))
    assert status.is_connected
    assert status.session_name.startswith("SID-")
    assert status.tcp_connections == "0"
    assert status.tcp_connections_count == 0
    assert not status.has_live_transport
    assert status.is_phantom
    assert status.outgoing_bytes == 0
    assert status.incoming_bytes == 0
    assert status.outgoing_packets == 0
    assert status.incoming_packets == 0


def test_account_status_connecting():
    status = parser.parse_account_status(load("accountstatus_connecting.txt"))
    assert status.is_connecting
    assert not status.is_connected
    assert not status.is_phantom
    assert status.outgoing_bytes == 0


def test_nic_list():
    nics = parser.parse_nic_list(load("niclist.txt"))
    assert len(nics) == 1
    assert nics[0].name == "vpn0"
    assert nics[0].enabled
    assert nics[0].mac == "5E17534E105A"


def test_empty_lists():
    assert parser.parse_cert_list(load("certlist_empty.txt")) == []
    assert parser.parse_secure_list(load("securelist_empty.txt")) == []


def test_keep_and_password():
    keep = parser.parse_keep(load("keepget.txt"))
    assert keep.host == "keepalive.softether.org"
    assert keep.protocol == "UDP/IP"
    assert not keep.enabled

    password = parser.parse_password(load("passwordget.txt"))
    assert not password.enabled


def test_check_pass_and_fail():
    passed = parser.parse_check(load("check_pass.txt"))
    assert passed.passed
    assert len(passed.items) == 6

    failed = parser.parse_check(load("check_fail.txt"))
    assert not failed.passed
    assert failed.items[-1].label == "Network system"
    assert not failed.items[-1].passed


def test_error_code_parsing():
    assert parser.parse_error_code(load("error_account_missing.txt")) == 36
    assert parser.parse_status(load("error_account_missing.txt")) is False
    assert parser.parse_error_code(load("versionget.txt")) is None


@pytest.mark.parametrize("name", ["certlist_empty.txt", "error_account_missing.txt"])
def test_table_pairs_ignores_noise(name):
    for key, _ in parser.table_pairs(load(name)):
        assert set(key) != {"-"}
        assert not key.startswith("Error occurred")
