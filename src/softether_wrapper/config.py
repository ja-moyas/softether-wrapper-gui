"""User preferences (QSettings) and autostart handling."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSettings

ORG_NAME = "softether-wrapper"
APP_NAME = "softether-wrapper"

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "softether-wrapper.desktop"

AUTOSTART_TEMPLATE = """[Desktop Entry]
Type=Application
Name=SoftEther VPN Wrapper
Comment=System tray wrapper for the SoftEther vpncmd client
Exec={exec_line}
Icon=softether-wrapper
Terminal=false
X-GNOME-Autostart-enabled=true
"""


@dataclass
class Preferences:
    monitor_interval_ms: int = 3000
    notifications: bool = True
    hide_on_close: bool = True
    autostart: bool = False
    default_account: str = ""
    tap_interface: str = "vpn_vpn0"
    show_ip: bool = True
    helper_retry_ms: int = 5000


class ConfigStore:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings(ORG_NAME, APP_NAME)

    def load(self) -> Preferences:
        s = self._settings
        return Preferences(
            monitor_interval_ms=int(str(s.value("monitor/interval_ms", 3000))),
            notifications=_to_bool(s.value("monitor/notifications", True)),
            hide_on_close=_to_bool(s.value("window/hide_on_close", True)),
            autostart=_to_bool(s.value("startup/autostart", False)),
            default_account=str(s.value("accounts/default", "")),
            tap_interface=str(s.value("network/tap_interface", "vpn_vpn0")),
            show_ip=_to_bool(s.value("network/show_ip", True)),
            helper_retry_ms=int(str(s.value("helper/retry_ms", 5000))),
        )

    def save(self, preferences: Preferences) -> None:
        s = self._settings
        s.setValue("monitor/interval_ms", preferences.monitor_interval_ms)
        s.setValue("monitor/notifications", preferences.notifications)
        s.setValue("window/hide_on_close", preferences.hide_on_close)
        s.setValue("startup/autostart", preferences.autostart)
        s.setValue("accounts/default", preferences.default_account)
        s.setValue("network/tap_interface", preferences.tap_interface)
        s.setValue("network/show_ip", preferences.show_ip)
        s.setValue("helper/retry_ms", preferences.helper_retry_ms)
        s.sync()


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def default_exec_line() -> str:
    return os.environ.get("SOFTETHER_WRAPPER_EXEC", "softether-wrapper")


def set_autostart(enabled: bool) -> None:
    """Create or remove the per-user XDG autostart entry (idempotent)."""
    if enabled:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            AUTOSTART_TEMPLATE.format(exec_line=default_exec_line()), encoding="utf-8"
        )
    else:
        try:
            AUTOSTART_FILE.unlink()
        except FileNotFoundError:
            pass


def autostart_enabled() -> bool:
    return AUTOSTART_FILE.exists()
