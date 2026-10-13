"""Main window: tabbed pages, menu and status bar."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ..config import Preferences
from ..dbus_client import MonitorSnapshot
from ..models import ConnectionState
from .account_page import AccountsPage
from .cert_page import CertPage
from .dashboard import DashboardPage
from .icons import state_icon
from .nic_page import NicPage
from .settings_dialog import SettingsDialog
from .tools_page import ToolsPage


class MainWindow(QMainWindow):
    def __init__(self, controller) -> None:
        super().__init__()
        self.controller = controller
        self.snapshot: MonitorSnapshot | None = None
        self.setWindowTitle("SoftEther VPN Wrapper")
        self.resize(940, 660)
        self.setWindowIcon(state_icon(ConnectionState.DISCONNECTED))

        self.dashboard = DashboardPage()
        self.accounts = AccountsPage(controller)
        self.nics = NicPage(controller)
        self.certs = CertPage(controller)
        self.tools = ToolsPage(controller)

        tabs = QTabWidget()
        tabs.addTab(self.dashboard, "Panel")
        tabs.addTab(self.accounts, "Cuentas")
        tabs.addTab(self.nics, "Adaptadores")
        tabs.addTab(self.certs, "Certificados")
        tabs.addTab(self.tools, "Herramientas")
        self.setCentralWidget(tabs)

        self.dashboard.connect_requested.connect(controller.connect_account)
        self.dashboard.disconnect_requested.connect(controller.disconnect_account)
        self.dashboard.service_requested.connect(controller.service_action)

        self._build_menu()
        self.statusBar().showMessage("Listo")

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Archivo")
        show_action = QAction("Mostrar en la bandeja", self)
        show_action.triggered.connect(self.controller.show_window)
        prefs_action = QAction("Preferencias…", self)
        prefs_action.triggered.connect(self._open_settings)
        quit_action = QAction("Salir", self)
        quit_action.triggered.connect(self.controller.quit)
        file_menu.addAction(show_action)
        file_menu.addAction(prefs_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("Ayuda")
        about_action = QAction("Acerca de", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    def _account_names(self) -> list[str]:
        if not self.snapshot:
            return []
        return [account.name for account in self.snapshot.accounts]

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.controller.prefs, self._account_names(), self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.controller.save_settings(dialog.result_preferences(self.controller.prefs))

    def _about(self) -> None:
        def _done(text: str) -> None:
            self.statusBar().showMessage("vpncmd: " + " ".join(text.split())[:120])

        self.controller.schedule(self.controller.client.about(), on_done=_done)

    # -- updates -----------------------------------------------------------
    def update_snapshot(self, snapshot: MonitorSnapshot, addresses: list[str]) -> None:
        self.snapshot = snapshot
        self.dashboard.update_snapshot(snapshot, addresses)
        self.accounts.update_snapshot(snapshot)
        self.nics.update_snapshot(snapshot)
        active = snapshot.connected_account
        if active:
            self.statusBar().showMessage(f"Conectado: {active.name} — {active.server}")
        else:
            self.statusBar().showMessage("Sin conexión")

    def set_error(self, message: str) -> None:
        self.statusBar().showMessage(message)

    def set_service_status(self, status: str) -> None:
        self.dashboard.set_service_status(status)

    def apply_preferences(self, prefs: Preferences) -> None:  # noqa: ARG002
        self.refresh_certs()

    def refresh_certs(self) -> None:
        self.certs._refresh()

    def selected_account_name(self) -> str | None:
        return self.accounts.selected_account()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self.controller.prefs.hide_on_close:
            event.ignore()
            self.hide()
            self.controller.notify("SoftEther VPN Wrapper", "La aplicación sigue en la bandeja")
        else:
            event.accept()
            self.controller.quit()
