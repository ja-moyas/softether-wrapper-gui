"""Tests for the phantom-session recovery policy and its wiring in the app."""

from __future__ import annotations

import asyncio
import os
import types
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from softether_wrapper import vpncmd_parser as parser  # noqa: E402
from softether_wrapper.config import Preferences  # noqa: E402
from softether_wrapper.dbus_client import HelperError, MonitorSnapshot  # noqa: E402
from softether_wrapper.models import AccountSummary, CommandOutcome, SessionStatus  # noqa: E402
from softether_wrapper.recovery import (  # noqa: E402
    RecoveryDecision,
    RecoverySettings,
    SessionRecovery,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeClock:
    """Monotonic clock the tests drive by hand."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(clock: FakeClock, **kwargs) -> SessionRecovery:
    return SessionRecovery(RecoverySettings(**kwargs), clock=clock)


def snapshot(account_status: str, session: SessionStatus) -> MonitorSnapshot:
    return MonitorSnapshot(
        accounts=[AccountSummary(name="MyVPN", status=account_status)],
        status=session,
    )


PHANTOM_SESSION = dict(
    session_status="Connection Completed (Session Established)",
    tcp_connections="0",
)
LIVE_SESSION = dict(
    session_status="Connection Completed (Session Established)",
    tcp_connections="2",
)


# --- policy ---------------------------------------------------------------
def test_needs_consecutive_phantom_samples():
    clock = FakeClock()
    recovery = make(clock, after_samples=3)
    assert recovery.observe(True) is RecoveryDecision.NONE
    assert recovery.observe(True) is RecoveryDecision.NONE
    assert recovery.observe(True) is RecoveryDecision.RECONNECT
    assert recovery.attempts == 1


def test_healthy_sample_clears_the_streak():
    clock = FakeClock()
    recovery = make(clock, after_samples=2)
    assert recovery.observe(True) is RecoveryDecision.NONE
    assert recovery.observe(False) is RecoveryDecision.NONE
    assert recovery.observe(True) is RecoveryDecision.NONE
    assert recovery.observe(True) is RecoveryDecision.RECONNECT


def test_cooldown_holds_back_a_second_attempt():
    clock = FakeClock()
    recovery = make(clock, after_samples=1, cooldown_s=60, grace_s=0.0)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT
    recovery.attempt_finished()

    assert recovery.observe(True) is RecoveryDecision.NONE  # inside the cooldown
    clock.advance(61)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT


def test_grace_swallows_samples_issued_right_after_a_reconnect():
    clock = FakeClock()
    recovery = make(clock, after_samples=1, cooldown_s=0, grace_s=30.0)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT
    recovery.attempt_finished()

    assert recovery.observe(True) is RecoveryDecision.NONE
    assert recovery.observe(True) is RecoveryDecision.NONE
    clock.advance(31)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT


def test_cooldown_outlives_the_grace_so_attempts_stay_spaced():
    """Two independent back-off layers: the cooldown still holds after the grace."""
    clock = FakeClock()
    recovery = make(clock, after_samples=1, cooldown_s=60, grace_s=30.0)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT
    recovery.attempt_finished()

    clock.advance(31)  # past the grace, still inside the cooldown
    assert recovery.observe(True) is RecoveryDecision.NONE
    clock.advance(30)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT


def test_exhaustion_is_reported_once():
    clock = FakeClock()
    recovery = make(clock, after_samples=1, cooldown_s=1, max_attempts=2, grace_s=0.0)
    for _ in range(2):
        assert recovery.observe(True) is RecoveryDecision.RECONNECT
        recovery.attempt_finished()
        clock.advance(2)

    assert recovery.observe(True) is RecoveryDecision.EXHAUSTED
    assert recovery.observe(True) is RecoveryDecision.NONE


def test_healthy_sample_restores_the_attempt_budget_after_the_grace():
    clock = FakeClock()
    recovery = make(clock, after_samples=1, max_attempts=1, grace_s=5.0)
    assert recovery.observe(True) is RecoveryDecision.RECONNECT
    recovery.attempt_finished()

    recovery.observe(False)
    assert recovery.attempts == 1  # the grace still protects the budget

    clock.advance(6)
    recovery.observe(False)
    assert recovery.attempts == 0


def test_in_grace_flag():
    clock = FakeClock()
    recovery = make(clock, grace_s=10.0)
    assert not recovery.in_grace
    recovery.attempt_finished()
    assert recovery.in_grace
    clock.advance(11)
    assert not recovery.in_grace


def test_busy_defers_without_consuming_the_budget():
    clock = FakeClock()
    recovery = make(clock, after_samples=2)
    assert recovery.observe(True, busy=True) is RecoveryDecision.NONE
    assert recovery.observe(True, busy=True) is RecoveryDecision.NONE
    assert recovery.attempts == 0
    assert recovery.observe(True) is RecoveryDecision.RECONNECT


def test_disabled_never_reconnects():
    clock = FakeClock()
    recovery = make(clock, enabled=False, after_samples=1)
    for _ in range(5):
        assert recovery.observe(True) is RecoveryDecision.NONE


# --- detection ------------------------------------------------------------
def test_snapshot_is_phantom_only_while_the_account_is_linked():
    phantom = SessionStatus(**PHANTOM_SESSION)
    assert snapshot("Connected", phantom).is_phantom
    assert not snapshot("Disconnected", phantom).is_phantom

    assert not snapshot("Connected", SessionStatus(**LIVE_SESSION)).is_phantom
    connecting = SessionStatus(session_status="Connecting to VPN Server", tcp_connections="0")
    assert not snapshot("Connected", connecting).is_phantom


def test_snapshot_without_status_is_never_phantom():
    assert not MonitorSnapshot(accounts=[AccountSummary(name="MyVPN", status="Connected")]).is_phantom


def test_captured_phantom_fixture_drives_a_reconnect():
    """End to end: the captured output alone must trigger the repair."""
    text = (FIXTURES / "accountstatus_phantom.txt").read_text(encoding="utf-8")
    session = parser.parse_account_status(text)
    snap = snapshot("Connected", session)
    assert snap.is_phantom

    clock = FakeClock()
    recovery = make(clock, after_samples=3)
    decisions = [recovery.observe(snap.is_phantom) for _ in range(3)]
    assert decisions == [
        RecoveryDecision.NONE,
        RecoveryDecision.NONE,
        RecoveryDecision.RECONNECT,
    ]


# --- app wiring -----------------------------------------------------------
class RecordingClient:
    def __init__(self, fail_on: str = "") -> None:
        self.calls: list[str] = []
        self.fail_on = fail_on

    async def run_client(self, command, args=None):  # noqa: ANN001, ANN202, ARG002
        self.calls.append(command)
        if command == self.fail_on:
            return CommandOutcome(command, 36, "Error occurred. (Error code: 36)\n")
        return CommandOutcome(command, 0, "The command completed successfully.")


def test_recover_drops_the_session_before_reconnecting(monkeypatch):
    pytest.importorskip("PySide6")
    from softether_wrapper import app as app_module

    monkeypatch.setattr(app_module, "RECOVERY_PAUSE_S", 0)
    holder = types.SimpleNamespace(client=RecordingClient())

    assert asyncio.run(app_module.WrapperApp._recover(holder, "MyVPN")) == "MyVPN"
    assert holder.client.calls == ["AccountDisconnect", "AccountConnect"]


def test_recover_surfaces_a_failed_reconnect(monkeypatch):
    pytest.importorskip("PySide6")
    from softether_wrapper import app as app_module

    monkeypatch.setattr(app_module, "RECOVERY_PAUSE_S", 0)
    holder = types.SimpleNamespace(client=RecordingClient(fail_on="AccountConnect"))

    with pytest.raises(HelperError):
        asyncio.run(app_module.WrapperApp._recover(holder, "MyVPN"))
    assert holder.client.calls == ["AccountDisconnect", "AccountConnect"]


class Controller:
    """The slice of ``WrapperApp`` that ``_maybe_recover`` touches."""

    def __init__(self, recovery: SessionRecovery) -> None:
        self.prefs = Preferences(default_account="fallback")
        self.recovery = recovery
        self._recovering = False
        self._user_action_in_flight = False
        self.started: list[str] = []
        self.notifications: list[tuple[str, str, bool]] = []

    def _start_recovery(self, name: str) -> None:
        self.started.append(name)

    def notify(self, title: str, message: str, error: bool = False) -> None:
        self.notifications.append((title, message, error))


def test_maybe_recover_wires_the_policy_to_the_helper(monkeypatch):
    pytest.importorskip("PySide6")
    from softether_wrapper import app as app_module

    clock = FakeClock()
    controller = Controller(make(clock, after_samples=3))
    phantom = snapshot("Connected", SessionStatus(**PHANTOM_SESSION))
    healthy = snapshot("Connected", SessionStatus(**LIVE_SESSION))

    for _ in range(3):
        app_module.WrapperApp._maybe_recover(controller, phantom, "MyVPN")
    assert controller.started == ["MyVPN"]

    # A healthy session never triggers anything.
    controller.recovery.attempt_finished()
    controller.started.clear()
    for _ in range(5):
        app_module.WrapperApp._maybe_recover(controller, healthy, "MyVPN")
    assert controller.started == []


def test_maybe_recover_reports_exhaustion(monkeypatch):
    pytest.importorskip("PySide6")
    from softether_wrapper import app as app_module

    clock = FakeClock()
    controller = Controller(make(clock, after_samples=1, cooldown_s=1, max_attempts=1, grace_s=0.0))
    phantom = snapshot("Connected", SessionStatus(**PHANTOM_SESSION))

    app_module.WrapperApp._maybe_recover(controller, phantom, "MyVPN")
    assert controller.started == ["MyVPN"]
    controller.recovery.attempt_finished()

    clock.advance(5)
    for _ in range(3):
        app_module.WrapperApp._maybe_recover(controller, phantom, "MyVPN")

    assert controller.started == ["MyVPN"]  # the budget is spent
    assert [n[0] for n in controller.notifications] == ["VPN sin transporte"]
    assert controller.notifications[0][2] is True
    assert "intentos" in controller.notifications[0][1]


def test_maybe_recover_defers_while_a_user_action_is_in_flight(monkeypatch):
    pytest.importorskip("PySide6")
    from softether_wrapper import app as app_module

    clock = FakeClock()
    controller = Controller(make(clock, after_samples=1))
    controller._user_action_in_flight = True
    phantom = snapshot("Connected", SessionStatus(**PHANTOM_SESSION))

    app_module.WrapperApp._maybe_recover(controller, phantom, "MyVPN")
    assert controller.started == []

    controller._user_action_in_flight = False
    app_module.WrapperApp._maybe_recover(controller, phantom, "MyVPN")
    assert controller.started == ["MyVPN"]


def test_maybe_recover_skips_while_a_recovery_is_running(monkeypatch):
    pytest.importorskip("PySide6")
    from softether_wrapper import app as app_module

    clock = FakeClock()
    controller = Controller(make(clock, after_samples=1))
    controller._recovering = True
    phantom = snapshot("Connected", SessionStatus(**PHANTOM_SESSION))

    app_module.WrapperApp._maybe_recover(controller, phantom, "fallback")
    assert controller.started == []
