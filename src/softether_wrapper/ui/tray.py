"""System tray icon, its context menu and desktop notifications."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..models import ConnectionState
from .icons import state_icon


class TrayIcon(QSystemTrayIcon):
    def __init__(
        self,
        show_window: Callable[[], None],
        toggle_connection: Callable[[], None],
        quit_app: Callable[[], None],
        parent=None,
    ) -> None:
        super().__init__(state_icon(ConnectionState.DISCONNECTED), parent)
        self._show_window = show_window
        self._toggle_connection = toggle_connection
        self._state = ConnectionState.DISCONNECTED

        self._status_action = QAction("Sin conexión", self)
        self._status_action.setEnabled(False)
        self._connect_action = QAction("Conectar", self)
        self._connect_action.triggered.connect(lambda: self._toggle_connection())
        show_action = QAction("Mostrar ventana", self)
        show_action.triggered.connect(lambda: self._show_window())
        quit_action = QAction("Salir", self)
        quit_action.triggered.connect(lambda: self._quit(quit_app))

        menu = QMenu()
        menu.addAction(self._status_action)
        menu.addSeparator()
        menu.addAction(self._connect_action)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    @staticmethod
    def _quit(quit_app: Callable[[], None]) -> None:
        quit_app()

    def set_state(self, state: ConnectionState, tooltip: str, connected_account: str = "") -> None:
        self._state = state
        self.setIcon(state_icon(state))
        self.setToolTip(tooltip)
        if state is ConnectionState.CONNECTED:
            label = f"Conectado: {connected_account}" if connected_account else "Conectado"
            self._connect_action.setText("Desconectar")
        elif state is ConnectionState.STALE:
            label = "Sin transporte: reconectando…"
            self._connect_action.setText("Desconectar")
        elif state is ConnectionState.CONNECTING:
            label = "Conectando…"
            self._connect_action.setText("Cancelar conexión")
        else:
            label = "Sin conexión"
            self._connect_action.setText("Conectar")
        self._status_action.setText(label)

    @property
    def state(self) -> ConnectionState:
        return self._state

    def notify(self, title: str, message: str, error: bool = False) -> None:
        icon = QSystemTrayIcon.MessageIcon.Critical if error else QSystemTrayIcon.MessageIcon.Information
        if self.isSystemTrayAvailable():
            self.showMessage(title, message, icon, 5000)
