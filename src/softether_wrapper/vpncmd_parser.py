"""Parsers that turn raw ``vpncmd`` text into the dataclasses in :mod:`models`.

The formats are pinned to the fixtures under ``tests/fixtures`` which were
captured from a real ``vpncmd`` v5.01.  Every parser degrades gracefully: on an
unexpected format it returns an empty/partial object rather than raising, so
the UI can always fall back to the raw text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .models import (
    AccountDetail,
    AccountSummary,
    Certificate,
    CheckItem,
    CheckResult,
    KeepSettings,
    Nic,
    PasswordSettings,
    SessionStatus,
    VersionInfo,
    digits_to_int,
)

PAIR_SEPARATOR = "|"
_SUCCESS_MARKERS = ("The command completed successfully.", "The command terminated normally.")
_ERROR_RE = re.compile(r"Error occurred\. \(Error code: (\d+)\)")


def table_pairs(text: str) -> list[tuple[str, str]]:
    """Extract ``key | value`` pairs from vpncmd table output."""
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        if PAIR_SEPARATOR not in line:
            continue
        key, _, value = line.partition(PAIR_SEPARATOR)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if set(key) <= {"-"}:
            continue
        if key == "Item" and value == "Value":
            continue
        pairs.append((key, value))
    return pairs


def group_records(
    pairs: Sequence[tuple[str, str]], first_key: str | None = None
) -> list[dict[str, str]]:
    """Group flat pairs into records.

    A new record starts whenever ``first_key`` repeats.  For single-object
    commands (no repeated key) the result is a single record.
    """
    if not pairs:
        return []
    if first_key is None:
        first_key = pairs[0][0]
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for key, value in pairs:
        if key == first_key and first_key in current:
            records.append(current)
            current = {}
        current[key] = value
    if current:
        records.append(current)
    return records


def parse_status(text: str) -> bool:
    """True when the text contains a vpncmd success marker."""
    return any(marker in text for marker in _SUCCESS_MARKERS)


def parse_error_code(text: str) -> int | None:
    match = _ERROR_RE.search(text)
    return int(match.group(1)) if match else None


def _to_int(value: str) -> int:
    # Kept as an alias so existing callers (and the tests) keep working; the
    # implementation now lives in :mod:`models` because the session models need
    # it too and must not import the parser.
    return digits_to_int(value)


# ---------------------------------------------------------------------------
# Individual commands
# ---------------------------------------------------------------------------
def parse_version(text: str) -> VersionInfo:
    pairs = dict(table_pairs(text))
    return VersionInfo(
        product=pairs.get("Product Name", ""),
        version=pairs.get("Version Information", ""),
        build=pairs.get("Build Information", ""),
        process_id=pairs.get("Process ID", ""),
        os_type=pairs.get("OS Type", ""),
    )


def parse_about(text: str) -> str:
    """Return the vpncmd version string (e.g. ``Version 5.01 Build 9674``)."""
    match = re.search(r"Version \d+\.\d+ Build \d+", text)
    return match.group(0) if match else ""


def parse_account_list(text: str) -> list[AccountSummary]:
    pairs = table_pairs(text)
    records = group_records(pairs, "VPN Connection Setting Name")
    accounts: list[AccountSummary] = []
    for record in records:
        server = record.get("VPN Server Hostname", "")
        server = re.sub(r"\s*\(.*\)\s*$", "", server).strip()
        accounts.append(
            AccountSummary(
                name=record.get("VPN Connection Setting Name", ""),
                status=record.get("Status", ""),
                server=server,
                hub=record.get("Virtual Hub", ""),
                nic=record.get("Virtual Network Adapter Name", ""),
            )
        )
    return [a for a in accounts if a.name]


_ACCOUNT_GET_MAP = {
    "Destination VPN Server Host Name": "server_host",
    "Destination VPN Server Port Number": "server_port",
    "Destination VPN Server Virtual Hub Name": "hub",
    "Proxy Server Type": "proxy_type",
    "Verify Server Certificate": "verify_server_cert",
    "Device Name Used for Connection": "nic",
    "Authentication Type": "auth_type",
    "User Name": "username",
    "Number of TCP Connections to Use in VPN Communication": "max_tcp",
    "Interval between Establishing Each TCP Connection": "interval",
    "Connection Life of Each TCP Connection": "ttl",
    "Use Half Duplex Mode": "half_duplex",
    "Encryption by SSL": "encrypt",
    "Data Compression": "compress",
    "Connect by Bridge / Router Mode": "bridge",
    "Connect by Monitoring Mode": "monitor",
    "No Adjustment for Routing Table": "no_track",
    "Do not Use QoS Control Function": "no_qos",
    "Disable UDP Acceleration": "no_udp_accel",
}

_STATUS_MAP = {
    "Session Status": "session_status",
    "Server Name": "server_name",
    "Port Number": "port_number",
    "Server Product Name": "server_product",
    "Server Version": "server_version",
    "Server Build": "server_build",
    "Connection Started at": "connection_started",
    "Current Session has been Established since": "session_established",
    "Number of TCP Connections": "tcp_connections",
    "Maximum Number of TCP Connections": "max_tcp_connections",
    "Encryption": "encryption",
    "Use of Compression": "compression",
    "Physical Underlay Protocol": "underlay",
    "UDP Acceleration is Active": "udp_accel_active",
    "Session Name": "session_name",
}
_STATUS_INT_MAP = {
    "Outgoing Data Size": "outgoing_bytes",
    "Incoming Data Size": "incoming_bytes",
    "Outgoing Unicast Packets": "outgoing_packets",
    "Incoming Unicast Packets": "incoming_packets",
}


def parse_account_get(text: str) -> AccountDetail:
    pairs = dict(table_pairs(text))
    detail = AccountDetail(raw=pairs)
    for key, attr in _ACCOUNT_GET_MAP.items():
        if key in pairs:
            setattr(detail, attr, pairs[key])
    detail.name = pairs.get("VPN Connection Setting Name", "")
    return detail


def parse_account_status(text: str) -> SessionStatus:
    pairs = dict(table_pairs(text))
    status = SessionStatus(raw=pairs)
    status.name = pairs.get("VPN Connection Setting Name", "")
    for key, attr in _STATUS_MAP.items():
        if key in pairs:
            setattr(status, attr, pairs[key])
    for key, attr in _STATUS_INT_MAP.items():
        if key in pairs:
            setattr(status, attr, _to_int(pairs[key]))
    return status


def parse_nic_list(text: str) -> list[Nic]:
    pairs = table_pairs(text)
    records = group_records(pairs, "Virtual Network Adapter Name")
    nics: list[Nic] = []
    for record in records:
        name = record.get("Virtual Network Adapter Name", "")
        if not name:
            continue
        nics.append(
            Nic(
                name=name,
                status=record.get("Status", ""),
                mac=record.get("MAC Address", ""),
                version=record.get("Version", ""),
            )
        )
    return nics


def _parse_identifier_list(text: str) -> list[Certificate]:
    pairs = table_pairs(text)
    records = group_records(pairs)
    certs: list[Certificate] = []
    for record in records:
        if not record:
            continue
        identifier = next(iter(record))
        certs.append(Certificate(identifier=identifier, details=dict(record)))
    return certs


def parse_cert_list(text: str) -> list[Certificate]:
    return _parse_identifier_list(text)


def parse_secure_list(text: str) -> list[Certificate]:
    return _parse_identifier_list(text)


def parse_keep(text: str) -> KeepSettings:
    pairs = dict(table_pairs(text))
    return KeepSettings(
        host=pairs.get("Host Name", ""),
        port=pairs.get("Port Number", ""),
        interval=pairs.get("Packet Send Interval (Sec)", ""),
        protocol=pairs.get("Protocol", ""),
        status=pairs.get("Current Status", ""),
    )


def parse_password(text: str) -> PasswordSettings:
    pairs = dict(table_pairs(text))
    return PasswordSettings(
        set_password=pairs.get("Set Password", ""),
        remote_only=pairs.get("Request Password for Remote Operation Only", ""),
    )


_CHECK_LINE_RE = re.compile(r"^Checking '(.+?)'\.\.\.\s*(.*)$")
_CHECK_RESULT_RE = re.compile(r"^\s*(Pass|Fail)\s*$")


def parse_check(text: str) -> CheckResult:
    items: list[CheckItem] = []
    pending: CheckItem | None = None
    for line in text.splitlines():
        match = _CHECK_LINE_RE.match(line)
        if match:
            if pending is not None:
                items.append(pending)
            pending = CheckItem(label=match.group(1), passed=False, message=match.group(2).strip())
            continue
        if pending is not None:
            result = _CHECK_RESULT_RE.match(line)
            if result:
                pending.passed = result.group(1) == "Pass"
                items.append(pending)
                pending = None
            elif line.strip() and not line.startswith("Checking"):
                pending.message = line.strip()
    if pending is not None:
        items.append(pending)

    summary = ""
    for line in text.splitlines():
        if line.startswith("Some checks failed") or line.startswith("All checks"):
            summary = line.strip()
    return CheckResult(items=items, summary=summary)
