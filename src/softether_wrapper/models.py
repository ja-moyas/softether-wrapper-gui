"""Plain data models shared by the parser, the D-Bus client and the UI.

None of these objects depend on Qt, so they can be unit-tested in isolation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


def digits_to_int(value: object) -> int:
    """Coerce a vpncmd numeric field (``"1,703,088 bytes"``, ``"-"``) to ``int``.

    Shared by the parser (integer counters) and by the session models that need
    to compare a counter against zero.  Anything non-numeric yields ``0``.
    """
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


class ConnectionState(str, Enum):
    """State shown by the tray icon and the dashboard.

    ``STALE`` is always derived, never parsed out of ``vpncmd`` text: the client
    reports the account as connected but the tunnel carries no transport, so
    nothing reaches the remote network.
    """

    CONNECTED = "connected"
    CONNECTING = "connecting"
    DISCONNECTED = "disconnected"
    STALE = "stale"
    UNKNOWN = "unknown"

    @classmethod
    def from_status(cls, status: str | None) -> ConnectionState:
        if not status:
            return cls.UNKNOWN
        text = status.strip().lower()
        if "disconnect" in text or text == "offline":
            return cls.DISCONNECTED
        if "connecting" in text:
            return cls.CONNECTING
        if text == "connected" or "connection completed" in text or "established" in text:
            return cls.CONNECTED
        return cls.UNKNOWN


@dataclass
class AccountSummary:
    """One row of ``AccountList``."""

    name: str
    status: str = ""
    server: str = ""
    hub: str = ""
    nic: str = ""

    @property
    def state(self) -> ConnectionState:
        return ConnectionState.from_status(self.status)

    @property
    def is_connected(self) -> bool:
        """``True`` when the client *reports* this account as connected.

        This is the link state read from ``AccountList``.  It says nothing about
        whether the tunnel still transports traffic — see
        :attr:`SessionStatus.is_phantom` for that.
        """
        return self.state is ConnectionState.CONNECTED


@dataclass
class AccountDetail:
    """Result of ``AccountGet``."""

    name: str = ""
    server_host: str = ""
    server_port: str = ""
    hub: str = ""
    proxy_type: str = ""
    verify_server_cert: str = ""
    nic: str = ""
    auth_type: str = ""
    username: str = ""
    max_tcp: str = ""
    interval: str = ""
    ttl: str = ""
    half_duplex: str = ""
    encrypt: str = ""
    compress: str = ""
    bridge: str = ""
    monitor: str = ""
    no_track: str = ""
    no_qos: str = ""
    no_udp_accel: str = ""
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def server(self) -> str:
        if self.server_port:
            return f"{self.server_host}:{self.server_port}"
        return self.server_host


@dataclass
class SessionStatus:
    """Result of ``AccountStatusGet``."""

    name: str = ""
    session_status: str = ""
    server_name: str = ""
    port_number: str = ""
    server_product: str = ""
    server_version: str = ""
    server_build: str = ""
    connection_started: str = ""
    session_established: str = ""
    tcp_connections: str = ""
    max_tcp_connections: str = ""
    encryption: str = ""
    compression: str = ""
    underlay: str = ""
    udp_accel_active: str = ""
    session_name: str = ""
    outgoing_bytes: int = 0
    incoming_bytes: int = 0
    outgoing_packets: int = 0
    incoming_packets: int = 0
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def is_connected(self) -> bool:
        text = self.session_status.lower()
        return "connection completed" in text or "established" in text

    @property
    def is_connecting(self) -> bool:
        return "connecting" in self.session_status.lower()

    @property
    def tcp_connections_count(self) -> int:
        """``Number of TCP Connections`` as an integer."""
        return digits_to_int(self.tcp_connections)

    @property
    def has_live_transport(self) -> bool:
        """``True`` when at least one TCP connection to the server is alive."""
        return self.tcp_connections_count > 0

    @property
    def is_phantom(self) -> bool:
        """The session claims to be established but carries no transport.

        SoftEther keeps the session object (and the "Session Established" text)
        after the socket to the server dies — for instance when the notebook
        loses internet.  Every counter stays at zero, the TAP keeps its IP and
        route, and ARP to the remote network never resolves, so the connection
        looks fine while nothing can reach the server.
        """
        return self.is_connected and not self.has_live_transport


@dataclass
class Nic:
    """One row of ``NicList``."""

    name: str
    status: str = ""
    mac: str = ""
    version: str = ""

    @property
    def enabled(self) -> bool:
        return self.status.strip().lower() == "enabled"


@dataclass
class Certificate:
    """One entry of ``CertList`` / ``SecureList``."""

    identifier: str
    details: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        for key in ("Common Name", "Subject", "Name", "Value"):
            if key in self.details:
                return self.details[key]
        return ", ".join(f"{k}={v}" for k, v in self.details.items()) or self.identifier


@dataclass
class KeepSettings:
    host: str = ""
    port: str = ""
    interval: str = ""
    protocol: str = ""
    status: str = ""

    @property
    def enabled(self) -> bool:
        return self.status.strip().lower() in {"enable", "enabled", "yes"}


@dataclass
class PasswordSettings:
    set_password: str = ""
    remote_only: str = ""

    @property
    def enabled(self) -> bool:
        return self.set_password.strip().lower() in {"enable", "enabled", "yes"}


@dataclass
class VersionInfo:
    product: str = ""
    version: str = ""
    build: str = ""
    process_id: str = ""
    os_type: str = ""


@dataclass
class CheckItem:
    label: str
    passed: bool
    message: str = ""


@dataclass
class CheckResult:
    items: list[CheckItem] = field(default_factory=list)
    summary: str = ""

    @property
    def passed(self) -> bool:
        return bool(self.items) and all(item.passed for item in self.items)


@dataclass
class CommandOutcome:
    """Raw result of one helper invocation."""

    command: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        if self.exit_code != 0:
            return False
        return (
            "The command completed successfully." in self.stdout
            or "The command terminated normally." in self.stdout
        )

    @property
    def error_message(self) -> str:
        for line in self.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Error occurred.") or stripped.startswith("Error:"):
                return stripped
        return self.stderr.strip()
