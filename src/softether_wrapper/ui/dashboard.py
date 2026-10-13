"""Dashboard: live connection state, counters and service controls."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..dbus_client import MonitorSnapshot
from ..models import ConnectionState
from .util import human_bytes, human_duration


class DashboardPage(QWidget):
    connect_requested = Signal(str)
    disconnect_requested = Signal(str)
    service_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._account = ""

        self.state_label = QLabel("Sin conexión")
        font = QFont()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self.state_label.setFont(font)
        self.account_label = QLabel("—")

        header = QVBoxLayout()
        header.addWidget(self.state_label)
        header.addWidget(self.account_label)

        self._values: dict[str, QLabel] = {}
        form = QFormLayout()
        for key, label in (
            ("server", "Servidor"),
            ("hub", "Hub virtual"),
            ("nic", "Adaptador"),
            ("ip", "Dirección IP"),
            ("started", "Conectado desde"),
            ("duration", "Duración"),
            ("rx", "Bytes recibidos"),
            ("tx", "Bytes enviados"),
            ("packets", "Paquetes RX/TX"),
            ("encryption", "Cifrado"),
            ("compression", "Compresión"),
            ("udp", "Aceleración UDP"),
            ("version", "Cliente"),
            ("session", "Sesión"),
        ):
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self._values[key] = value
            form.addRow(f"{label}:", value)

        info_box = QGroupBox("Estado de la conexión")
        info_box.setLayout(form)

        self.connect_button = QPushButton("Conectar")
        self.connect_button.clicked.connect(self._on_connect)
        self.disconnect_button = QPushButton("Desconectar")
        self.disconnect_button.clicked.connect(self._on_disconnect)
        self.disconnect_button.setEnabled(False)
        actions = QHBoxLayout()
        actions.addWidget(self.connect_button)
        actions.addWidget(self.disconnect_button)
        actions.addStretch(1)

        self.service_label = QLabel("Servicio: desconocido")
        start = QPushButton("Iniciar")
        start.clicked.connect(lambda: self.service_requested.emit("start"))
        stop = QPushButton("Detener")
        stop.clicked.connect(lambda: self.service_requested.emit("stop"))
        restart = QPushButton("Reiniciar")
        restart.clicked.connect(lambda: self.service_requested.emit("restart"))
        service_row = QHBoxLayout()
        service_row.addWidget(self.service_label)
        service_row.addStretch(1)
        service_row.addWidget(start)
        service_row.addWidget(stop)
        service_row.addWidget(restart)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(info_box)
        layout.addLayout(actions)
        layout.addWidget(separator)
        layout.addLayout(service_row)
        layout.addStretch(1)
        self._grid = QGridLayout()

    def _on_connect(self) -> None:
        if self._account:
            self.connect_requested.emit(self._account)

    def _on_disconnect(self) -> None:
        if self._account:
            self.disconnect_requested.emit(self._account)

    def set_service_status(self, status: str) -> None:
        mapping = {
            "active": "Servicio: activo",
            "inactive": "Servicio: detenido",
            "failed": "Servicio: fallido",
            "activating": "Servicio: iniciando…",
        }
        self.service_label.setText(mapping.get(status, f"Servicio: {status}"))

    def update_snapshot(self, snapshot: MonitorSnapshot, addresses: list[str]) -> None:
        active = snapshot.connected_account
        status = snapshot.status
        self._account = active.name if active else (status.name if status else "")

        if status and status.is_connected:
            state = ConnectionState.CONNECTED
        elif status and status.is_connecting:
            state = ConnectionState.CONNECTING
        elif active is not None:
            state = active.state
        else:
            state = ConnectionState.DISCONNECTED

        labels = {
            ConnectionState.CONNECTED: "Conectado",
            ConnectionState.CONNECTING: "Conectando…",
            ConnectionState.DISCONNECTED: "Sin conexión",
            ConnectionState.UNKNOWN: "Estado desconocido",
        }
        self.state_label.setText(labels.get(state, "—"))
        self.account_label.setText(f"Cuenta: {self._account}" if self._account else "—")
        self.connect_button.setEnabled(state is not ConnectionState.CONNECTED)
        self.disconnect_button.setEnabled(
            state in (ConnectionState.CONNECTED, ConnectionState.CONNECTING)
        )

        server = ""
        hub = ""
        nic = ""
        if active:
            hub = active.hub
            nic = active.nic
        if status and status.is_connected:
            server = status.server_name
            if status.port_number:
                server = f"{server} ({status.port_number})"
        elif active:
            server = active.server

        self._values["server"].setText(server or "—")
        self._values["hub"].setText(hub or "—")
        self._values["nic"].setText(nic or "—")
        self._values["ip"].setText(", ".join(addresses) if addresses else "—")
        self._values["version"].setText(snapshot.version or "—")

        if status and status.is_connected:
            self._values["started"].setText(status.connection_started or "—")
            self._values["duration"].setText(human_duration(status.connection_started, datetime.now()))
            self._values["rx"].setText(human_bytes(status.incoming_bytes))
            self._values["tx"].setText(human_bytes(status.outgoing_bytes))
            self._values["packets"].setText(
                f"{status.incoming_packets:,} / {status.outgoing_packets:,}"
            )
            self._values["encryption"].setText(status.encryption or "—")
            self._values["compression"].setText(status.compression or "—")
            self._values["udp"].setText(status.udp_accel_active or "—")
            self._values["session"].setText(status.session_name or "—")
        else:
            for key in ("started", "duration", "rx", "tx", "packets", "encryption", "compression", "udp", "session"):
                self._values[key].setText("—")
