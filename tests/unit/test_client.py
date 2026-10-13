from dbus_next import Variant

from softether_wrapper.dbus_client import MonitorSnapshot, _marshal, _outcome
from softether_wrapper.models import AccountSummary, SessionStatus


def test_marshal_wraps_variants():
    out = _marshal({"name": "MyVPN", "SERVER": "vpn.example.com:443"})
    assert out["name"] == Variant("s", "MyVPN")
    assert out["SERVER"].value == "vpn.example.com:443"


def test_outcome_from_tuple():
    outcome = _outcome("VersionGet", [0, "ok", ""])
    assert outcome.exit_code == 0
    assert outcome.stdout == "ok"
    assert outcome.command == "VersionGet"


def test_outcome_coerces_string_code():
    outcome = _outcome("X", ["36", "err", ""])
    assert outcome.exit_code == 36


def test_snapshot_connected_account():
    snapshot = MonitorSnapshot(
        accounts=[
            AccountSummary(name="first", status="Disconnected"),
            AccountSummary(name="second", status="Connected"),
        ]
    )
    assert snapshot.connected_account is not None
    assert snapshot.connected_account.name == "second"


def test_snapshot_without_connected_account():
    snapshot = MonitorSnapshot(accounts=[AccountSummary(name="only", status="Disconnected")])
    assert snapshot.connected_account is None


def test_snapshot_is_phantom_needs_link_and_status():
    session = SessionStatus(
        session_status="Connection Completed (Session Established)", tcp_connections="0"
    )
    linked = MonitorSnapshot(
        accounts=[AccountSummary(name="second", status="Connected")], status=session
    )
    assert linked.is_phantom

    # No AccountStatusGet result yet: the link alone proves nothing.
    unlinked = MonitorSnapshot(accounts=[AccountSummary(name="second", status="Connected")])
    assert not unlinked.is_phantom

    # A healthy tunnel is never phantom, however the counters read.
    healthy = MonitorSnapshot(
        accounts=[AccountSummary(name="second", status="Connected")],
        status=SessionStatus(
            session_status="Connection Completed (Session Established)", tcp_connections="2"
        ),
    )
    assert not healthy.is_phantom
