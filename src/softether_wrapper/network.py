"""Read-only helpers for inspecting the local TAP interface.

The wrapper never configures the interface IP: that is owned by the external
``vpn-tap-ip.service``.  We only display what is already configured.
"""

from __future__ import annotations

import json
import shutil
import subprocess

DEFAULT_TAP_NAME = "vpn_vpn0"


def _ip_command() -> list[str]:
    ip = shutil.which("ip")
    return [ip] if ip else []


def tap_addresses(interface: str = DEFAULT_TAP_NAME, timeout: float = 3.0) -> list[str]:
    """Return the IPv4/IPv6 addresses currently assigned to ``interface``."""
    ip = _ip_command()
    if not ip:
        return []
    try:
        completed = subprocess.run(
            [*ip, "-j", "addr", "show", interface],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if completed.returncode != 0:
        return []
    try:
        data = json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return []
    addresses: list[str] = []
    for link in data:
        for info in link.get("addr_info", []):
            address = info.get("local")
            if address:
                prefix = info.get("prefixlen")
                addresses.append(f"{address}/{prefix}" if prefix is not None else address)
    return addresses


def tap_is_up(interface: str = DEFAULT_TAP_NAME) -> bool:
    ip = _ip_command()
    if not ip:
        return False
    try:
        completed = subprocess.run(
            [*ip, "-j", "link", "show", interface],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if completed.returncode != 0:
        return False
    try:
        data = json.loads(completed.stdout.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return False
    return bool(data) and data[0].get("operstate") not in {"DOWN", "LOWERLAYERDOWN"}
