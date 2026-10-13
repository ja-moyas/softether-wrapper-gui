"""Application controller: single instance, tray, monitoring loop and wiring."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Callable

import qasync
from PySide6.QtCore import QDir, QLockFile, QObject, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import config
from .config import ConfigStore, Preferences
from .dbus_client import HelperClient, HelperError, MonitorSnapshot
from .models import AccountSummary, ConnectionState
from .network import tap_addresses
from .ui.main_window import MainWindow
from .ui.tray import TrayIcon

log = logging.getLogger("softether-wrapper")

APP_DISPLAY_NAME = "SoftEther VPN Wrapper"
LOCK_FILE = "softether-wrapper.lock"


class WrapperApp(QObject):
    def __init__(self, qt_app: QApplication) -> None:
        super().__init__()
        self.qt_app = qt_app
        self.qt_app.setApplicationName(config.APP_NAME)
        self.qt_app.setApplicationDisplayName(APP_DISPLAY_NAME)
        self.qt_app.setQuitOnLastWindowClosed(False)

        self.store = ConfigStore()
        self.prefs: Preferences = self.store.load()
        self.client = HelperClient()

        self.tray = TrayIcon(
            show_window=self.show_window,
            toggle_connection=self.toggle_connection,
            quit_app=self.quit,
        )
        self.window = MainWindow(self)

        self._monitor_task: asyncio.Task | None = None
        self._last_state: ConnectionState | None = None
        self._first_snapshot = True
        self._last_error = ""

        self._timer = QTimer(self)
        self._timer.setInterval(max(1000, self.prefs.monitor_interval_ms))
        self._timer.timeout.connect(self.refresh)

        self.tray.show()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.setVisible(True)
        self.window.show()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._timer.start()
        self.window.refresh_certs()
        self.refresh()

    def quit(self) -> None:
        self._timer.stop()
        self.store.save(self.prefs)
        task = asyncio.ensure_future(self.client.close())
        task.add_done_callback(lambda _t: self.qt_app.quit())

    # -- helpers -----------------------------------------------------------
    def schedule(
        self,
        coro,
        on_done: Callable | None = None,
        on_error: Callable | None = None,
    ) -> asyncio.Task:
        task = asyncio.ensure_future(coro)

        def _finished(t: asyncio.Task) -> None:
            try:
                result = t.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("task failed: %s", exc)
                if on_error is not None:
                    on_error(exc)
                else:
                    self.notify("Error", str(exc), error=True)
            else:
                if on_done is not None:
                    on_done(result)

        task.add_done_callback(_finished)
        return task

    def notify(self, title: str, message: str, error: bool = False) -> None:
        if self.prefs.notifications or error:
            self.tray.notify(title, message, error=error)

    def apply_preferences(self, prefs: Preferences) -> None:
        self.prefs = prefs
        self.store.save(prefs)
        config.set_autostart(prefs.autostart)
        self._timer.setInterval(max(1000, prefs.monitor_interval_ms))

    # -- window ------------------------------------------------------------
    def show_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    # -- monitoring --------------------------------------------------------
    def refresh(self) -> None:
        if self._monitor_task is not None and not self._monitor_task.done():
            return
        self._monitor_task = self.schedule(
            self.client.monitor(self.prefs.default_account),
            on_done=self._apply_snapshot,
            on_error=self._on_monitor_error,
        )
        self.schedule(
            self.client.client_service_status(),
            on_done=self.window.set_service_status,
            on_error=lambda _exc: None,
        )

    def _on_monitor_error(self, exc: Exception) -> None:
        state = ConnectionState.UNKNOWN
        detail = f"Sin conexión con el helper: {exc}"
        self.tray.set_state(state, detail)
        self.window.set_error(detail)

    def _apply_snapshot(self, snapshot: MonitorSnapshot) -> None:
        if snapshot.error:
            self._on_monitor_error(HelperError(snapshot.error))
            return

        active = snapshot.connected_account
        if snapshot.status and snapshot.status.is_connected:
            state = ConnectionState.CONNECTED
        elif snapshot.status and snapshot.status.is_connecting:
            state = ConnectionState.CONNECTING
        elif active is not None:
            state = active.state
        else:
            state = ConnectionState.DISCONNECTED

        addresses = []
        if self.prefs.show_ip:
            addresses = tap_addresses(self.prefs.tap_interface)

        tooltip = self._build_tooltip(state, snapshot, addresses)
        account_name = active.name if active else (snapshot.status.name if snapshot.status else "")
        self.tray.set_state(state, tooltip, account_name)
        self.window.update_snapshot(snapshot, addresses)

        if (
            not self._first_snapshot
            and self.prefs.notifications
            and state is not self._last_state
        ):
            self._notify_transition(state, account_name)
        self._first_snapshot = False
        self._last_state = state

    @staticmethod
    def _build_tooltip(
        state: ConnectionState, snapshot: MonitorSnapshot, addresses: list[str]
    ) -> str:
        lines = [f"SoftEther VPN Wrapper — {state.value}"]
        active = snapshot.connected_account
        if active:
            lines.append(f"Cuenta: {active.name}")
            lines.append(f"Servidor: {active.server}")
        status = snapshot.status
        if status and status.is_connected:
            lines.append(f"RX: {status.incoming_bytes:,} bytes")
            lines.append(f"TX: {status.outgoing_bytes:,} bytes")
        if addresses:
            lines.append("IP: " + ", ".join(addresses))
        if snapshot.version:
            lines.append(snapshot.version)
        return "\n".join(lines)

    def _notify_transition(self, state: ConnectionState, account_name: str) -> None:
        if state is ConnectionState.CONNECTED:
            self.notify("VPN conectada", f"Cuenta: {account_name or 'activa'}")
        elif state is ConnectionState.CONNECTING:
            self.notify("Conectando VPN", account_name or "Iniciando conexión…")
        elif state is ConnectionState.DISCONNECTED:
            self.notify("VPN desconectada", "La conexión se ha cerrado")

    # -- actions -----------------------------------------------------------
    def connect_account(self, name: str) -> None:
        self.schedule(
            self.client.run_client("AccountConnect", {"name": name}),
            on_done=lambda outcome: self._after_action("Conectar", name, outcome),
        )

    def disconnect_account(self, name: str) -> None:
        self.schedule(
            self.client.run_client("AccountDisconnect", {"name": name}),
            on_done=lambda outcome: self._after_action("Desconectar", name, outcome),
        )

    def toggle_connection(self) -> None:
        snapshot: MonitorSnapshot | None = self.window.snapshot
        active: AccountSummary | None = snapshot.connected_account if snapshot else None
        if self._last_state is ConnectionState.CONNECTED and active is not None:
            self.disconnect_account(active.name)
        elif active is None:
            name = self.window.selected_account_name() or self.prefs.default_account
            if name:
                self.connect_account(name)
            else:
                self.notify("VPN", "No hay ninguna cuenta seleccionada", error=True)

    def _after_action(self, action: str, name: str, outcome) -> None:
        if outcome.exit_code != 0:
            self.notify(
                f"Error al {action.lower()}",
                outcome.error_message or f"código {outcome.exit_code}",
                error=True,
            )
        self.refresh()

    def service_action(self, action: str) -> None:
        method = {
            "start": self.client.client_service_start,
            "stop": self.client.client_service_stop,
            "restart": self.client.client_service_restart,
        }.get(action)
        if method is None:
            return
        self.schedule(
            method(),
            on_done=lambda _out: self.refresh(),
            on_error=lambda exc: self.notify("Servicio", str(exc), error=True),
        )

    def save_settings(self, prefs: Preferences) -> None:
        self.apply_preferences(prefs)
        self.window.apply_preferences(prefs)

    # -- errors ------------------------------------------------------------
    def fatal(self, message: str) -> None:
        QMessageBox.critical(self.window, "SoftEther VPN Wrapper", message)


def _already_running() -> bool:
    lock = QLockFile(os.path.join(QDir.tempPath(), LOCK_FILE))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        _already_running.lock = lock  # type: ignore[attr-defined]
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    argv = list(sys.argv if argv is None else argv)
    qt_app = QApplication(argv)
    if _already_running():
        if QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.information(
                None, APP_DISPLAY_NAME, "La aplicación ya se está ejecutando."
            )
        return 0

    loop = qasync.QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    controller = WrapperApp(qt_app)
    with loop:
        controller.start()
        loop.run_forever()
    return 0
