from datetime import datetime

from softether_wrapper.models import (
    Certificate,
    CommandOutcome,
    ConnectionState,
    KeepSettings,
    Nic,
    PasswordSettings,
    SessionStatus,
    digits_to_int,
)
from softether_wrapper.ui.util import human_bytes, human_duration


def test_connection_state_from_status():
    assert ConnectionState.from_status("Connected") is ConnectionState.CONNECTED
    assert ConnectionState.from_status("Disconnected") is ConnectionState.DISCONNECTED
    assert ConnectionState.from_status("Connecting to VPN Server") is ConnectionState.CONNECTING
    assert (
        ConnectionState.from_status("Connection Completed (Session Established)")
        is ConnectionState.CONNECTED
    )
    assert ConnectionState.from_status("") is ConnectionState.UNKNOWN
    assert ConnectionState.from_status("weird") is ConnectionState.UNKNOWN


def test_session_status_flags():
    status = SessionStatus(session_status="Connection Completed (Session Established)")
    assert status.is_connected and not status.is_connecting
    connecting = SessionStatus(session_status="Connecting to VPN Server")
    assert connecting.is_connecting and not connecting.is_connected


def test_stale_is_derived_never_parsed():
    assert ConnectionState.from_status("Stale") is ConnectionState.UNKNOWN


def test_session_status_transport_flags():
    phantom = SessionStatus(
        session_status="Connection Completed (Session Established)", tcp_connections="0"
    )
    assert phantom.is_connected
    assert phantom.tcp_connections_count == 0
    assert not phantom.has_live_transport
    assert phantom.is_phantom

    live = SessionStatus(
        session_status="Connection Completed (Session Established)", tcp_connections="2"
    )
    assert live.has_live_transport
    assert not live.is_phantom

    connecting = SessionStatus(session_status="Connecting to VPN Server", tcp_connections="0")
    assert not connecting.is_phantom


def test_digits_to_int_tolerates_vpncmd_formatting():
    assert digits_to_int("1,703,088 bytes") == 1703088
    assert digits_to_int("2") == 2
    assert digits_to_int("0 packets") == 0
    assert digits_to_int("-") == 0
    assert digits_to_int("") == 0
    assert digits_to_int(None) == 0
    assert digits_to_int(7) == 7


def test_command_outcome():
    ok = CommandOutcome("X", 0, "The command completed successfully.")
    assert ok.ok
    bad = CommandOutcome("X", 36, "Error occurred. (Error code: 36)\n")
    assert not bad.ok
    assert bad.error_message == "Error occurred. (Error code: 36)"


def test_small_models():
    assert Nic(name="vpn0", status="Enabled").enabled
    assert not Nic(name="vpn0", status="Disabled").enabled
    assert KeepSettings(status="Enable").enabled
    assert PasswordSettings(set_password="Disable").enabled is False
    assert PasswordSettings(set_password="Enable").enabled


def test_certificate_label():
    cert = Certificate(identifier="1", details={"Common Name": "example.com"})
    assert cert.label == "example.com"
    empty = Certificate(identifier="7", details={})
    assert empty.label == "7"


def test_human_bytes():
    assert human_bytes(0) == "0 B"
    assert human_bytes(1024) == "1.00 KiB"
    assert human_bytes(1703088) == "1.62 MiB"


def test_human_duration():
    assert (
        human_duration("2026-10-09 (Fri) 17:49:40", datetime(2026, 10, 9, 18, 49, 40))
        == "01:00:00"
    )
    assert human_duration("") == "-"
    assert human_duration("not a date") == "not a date"
