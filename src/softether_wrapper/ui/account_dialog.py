"""Tabbed editor for a VPN connection setting (an ``Account*`` command set)."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..models import AccountDetail, Nic

Command = tuple[str, dict[str, str]]


class _PathRow(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.edit = QLineEdit()
        browse = QPushButton("…")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)
        layout.addWidget(browse)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Seleccionar archivo")
        if path:
            self.edit.setText(path)

    def text(self) -> str:
        return self.edit.text().strip()

    def setText(self, value: str) -> None:
        self.edit.setText(value)


class AccountDialog(QDialog):
    def __init__(
        self,
        nics: list[Nic] | None = None,
        detail: AccountDetail | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._original_name = detail.name if detail else ""
        self._is_new = detail is None
        self.setWindowTitle("Nueva cuenta" if self._is_new else f"Editar: {self._original_name}")
        self.setMinimumWidth(520)

        self.name = QLineEdit()
        self.server_host = QLineEdit()
        self.server_port = QLineEdit("443")
        self.hub = QLineEdit()
        self.username = QLineEdit()
        self.nic = QComboBox()
        self.nic.setEditable(True)
        for nic in nics or []:
            self.nic.addItem(nic.name)
        if self.nic.count() == 0:
            self.nic.addItem("vpn0")

        # Authentication
        self.auth_type = QComboBox()
        self.auth_type.addItems(["Anónima", "Contraseña", "Certificado cliente"])
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_type = QComboBox()
        self.password_type.addItems(["standard", "radius"])
        self.client_cert = _PathRow()
        self.client_key = _PathRow()

        # Proxy
        self.proxy_mode = QComboBox()
        self.proxy_mode.addItems(["Ninguno", "HTTP", "SOCKS"])
        self.proxy_server = QLineEdit()
        self.proxy_user = QLineEdit()
        self.proxy_password = QLineEdit()
        self.proxy_password.setEchoMode(QLineEdit.EchoMode.Password)

        # Security
        self.verify_cert = QCheckBox("Verificar el certificado del servidor")
        self.encrypt = QCheckBox("Cifrado SSL")
        self.compress = QCheckBox("Compresión de datos")
        self.server_cert = _PathRow()

        # Advanced
        self.max_tcp = QSpinBox()
        self.max_tcp.setRange(1, 32)
        self.max_tcp.setValue(1)
        self.interval = QSpinBox()
        self.interval.setRange(0, 3600)
        self.interval.setValue(1)
        self.ttl = QSpinBox()
        self.ttl.setRange(0, 86400)
        self.half = QCheckBox("Modo semidúplex")
        self.bridge = QCheckBox("Bridge / Router mode")
        self.monitor = QCheckBox("Monitoring mode")
        self.no_track = QCheckBox("No ajustar la tabla de rutas")
        self.no_qos = QCheckBox("Desactivar VoIP / QoS")

        # Connection
        self.startup = QCheckBox("Conectar al iniciar el servicio")
        self.retry_num = QSpinBox()
        self.retry_num.setRange(0, 999)
        self.retry_interval = QSpinBox()
        self.retry_interval.setRange(0, 86400)

        tabs = QTabWidget()
        tabs.addTab(self._basic_tab(), "Básico")
        tabs.addTab(self._auth_tab(), "Autenticación")
        tabs.addTab(self._proxy_tab(), "Proxy")
        tabs.addTab(self._security_tab(), "Certificados")
        tabs.addTab(self._advanced_tab(), "Avanzado")
        tabs.addTab(self._connection_tab(), "Conexión")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        if detail is not None:
            self._apply_detail(detail)

    # -- tabs --------------------------------------------------------------
    def _basic_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("Nombre:", self.name)
        form.addRow("Servidor:", self.server_host)
        form.addRow("Puerto:", self.server_port)
        form.addRow("Hub virtual:", self.hub)
        form.addRow("Usuario:", self.username)
        form.addRow("Adaptador:", self.nic)
        return widget

    def _auth_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("Tipo:", self.auth_type)
        form.addRow("Contraseña:", self.password)
        form.addRow("Tipo de contraseña:", self.password_type)
        form.addRow("Certificado cliente:", self.client_cert)
        form.addRow("Clave privada:", self.client_key)
        return widget

    def _proxy_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("Modo:", self.proxy_mode)
        form.addRow("Servidor:", self.proxy_server)
        form.addRow("Usuario:", self.proxy_user)
        form.addRow("Contraseña:", self.proxy_password)
        return widget

    def _security_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(self.verify_cert)
        form.addRow(self.encrypt)
        form.addRow(self.compress)
        form.addRow("Certificado del servidor:", self.server_cert)
        return widget

    def _advanced_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("Conexiones TCP (1-32):", self.max_tcp)
        form.addRow("Intervalo TCP (s):", self.interval)
        form.addRow("Vida de conexión TCP (s):", self.ttl)
        form.addRow(self.half)
        form.addRow(self.bridge)
        form.addRow(self.monitor)
        form.addRow(self.no_track)
        form.addRow(self.no_qos)
        return widget

    def _connection_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow(self.startup)
        form.addRow("Reintentos:", self.retry_num)
        form.addRow("Intervalo de reintento (s):", self.retry_interval)
        return widget

    # -- prefill -----------------------------------------------------------
    def _apply_detail(self, detail: AccountDetail) -> None:
        self.name.setText(detail.name)
        self.server_host.setText(detail.server_host)
        self.server_port.setText(detail.server_port or "443")
        self.hub.setText(detail.hub)
        self.username.setText(detail.username)
        self.nic.setCurrentText(detail.nic or "vpn0")

        auth = detail.auth_type.lower()
        if "cert" in auth:
            self.auth_type.setCurrentIndex(2)
        elif "password" in auth or "radius" in auth:
            self.auth_type.setCurrentIndex(1)
        elif "anonymous" in auth:
            self.auth_type.setCurrentIndex(0)

        proxy = detail.proxy_type.lower()
        if "http" in proxy:
            self.proxy_mode.setCurrentIndex(1)
        elif "socks" in proxy:
            self.proxy_mode.setCurrentIndex(2)
        else:
            self.proxy_mode.setCurrentIndex(0)

        self.verify_cert.setChecked(detail.verify_server_cert.lower() == "enable")
        self.encrypt.setChecked(detail.encrypt.lower() == "enable")
        self.compress.setChecked(detail.compress.lower() == "enable")

        if detail.max_tcp.isdigit():
            self.max_tcp.setValue(int(detail.max_tcp))
        if detail.interval.isdigit():
            self.interval.setValue(int(detail.interval))
        self.half.setChecked(detail.half_duplex.lower() == "enable")
        self.bridge.setChecked(detail.bridge.lower() == "enable")
        self.monitor.setChecked(detail.monitor.lower() == "enable")
        self.no_track.setChecked(detail.no_track.lower() == "enable")
        self.no_qos.setChecked(detail.no_qos.lower() == "enable")

    # -- command construction ---------------------------------------------
    def build_commands(self) -> list[Command]:
        name = self.name.text().strip()
        if not name:
            raise ValueError("El nombre de la cuenta es obligatorio")
        self._name = name
        commands: list[Command] = []

        server = self.server_host.text().strip()
        port = self.server_port.text().strip() or "443"
        if not self._is_new:
            if name != self._original_name:
                commands.append(("AccountRename", {"name": self._original_name, "NEW": name}))
            set_args: dict[str, str] = {}
            if server:
                set_args["SERVER"] = f"{server}:{port}"
            hub = self.hub.text().strip()
            if hub:
                set_args["HUB"] = hub
            if set_args:
                commands.append(("AccountSet", {"name": name, **set_args}))
        else:
            create_args = {"name": name, "NICNAME": self.nic.currentText().strip() or "vpn0"}
            if server:
                create_args["SERVER"] = f"{server}:{port}"
            hub = self.hub.text().strip()
            if hub:
                create_args["HUB"] = hub
            username = self.username.text().strip()
            if username:
                create_args["USERNAME"] = username
            commands.append(("AccountCreate", create_args))

        self._append_auth(commands, name)
        self._append_proxy(commands, name)
        self._append_flags(commands, name)
        self._append_detail(commands, name)
        self._append_retry(commands, name)
        commands.append(
            ("AccountStartupSet" if self.startup.isChecked() else "AccountStartupRemove", {"name": name})
        )
        return commands

    def _append_auth(self, commands: list[Command], name: str) -> None:
        mode = self.auth_type.currentIndex()
        if mode == 0:
            commands.append(("AccountAnonymousSet", {"name": name}))
        elif mode == 1:
            args = {"name": name, "TYPE": self.password_type.currentText()}
            if self.password.text():
                args["PASSWORD"] = self.password.text()
            commands.append(("AccountPasswordSet", args))
        else:
            cert = self.client_cert.text()
            key = self.client_key.text()
            if cert and key:
                commands.append(("AccountCertSet", {"name": name, "LOADCERT": cert, "LOADKEY": key}))

    def _append_proxy(self, commands: list[Command], name: str) -> None:
        mode = self.proxy_mode.currentIndex()
        server = self.proxy_server.text().strip()
        user = self.proxy_user.text().strip()
        password = self.proxy_password.text()
        if mode == 0:
            commands.append(("AccountProxyNone", {"name": name}))
        elif mode == 1:
            args = {"name": name}
            if server:
                args["SERVER"] = server
            if user:
                args["USERNAME"] = user
            if password:
                args["PASSWORD"] = password
            commands.append(("AccountProxyHttp", args))
        else:
            args = {"name": name}
            if server:
                args["SERVER"] = server
            if user:
                args["USERNAME"] = user
            if password:
                args["PASSWORD"] = password
            commands.append(("AccountProxySocks", args))

    def _append_flags(self, commands: list[Command], name: str) -> None:
        commands.append(
            (
                "AccountServerCertEnable" if self.verify_cert.isChecked() else "AccountServerCertDisable",
                {"name": name},
            )
        )
        commands.append(
            ("AccountEncryptEnable" if self.encrypt.isChecked() else "AccountEncryptDisable", {"name": name})
        )
        commands.append(
            ("AccountCompressEnable" if self.compress.isChecked() else "AccountCompressDisable", {"name": name})
        )
        server_cert = self.server_cert.text()
        if server_cert:
            commands.append(("AccountServerCertSet", {"name": name, "LOADCERT": server_cert}))

    def _append_detail(self, commands: list[Command], name: str) -> None:
        commands.append(
            (
                "AccountDetailSet",
                {
                    "name": name,
                    "MAXTCP": str(self.max_tcp.value()),
                    "INTERVAL": str(self.interval.value()),
                    "TTL": str(self.ttl.value()),
                    "HALF": _yes(self.half.isChecked()),
                    "BRIDGE": _yes(self.bridge.isChecked()),
                    "MONITOR": _yes(self.monitor.isChecked()),
                    "NOTRACK": _yes(self.no_track.isChecked()),
                    "NOQOS": _yes(self.no_qos.isChecked()),
                },
            )
        )

    def _append_retry(self, commands: list[Command], name: str) -> None:
        if self.retry_num.value() or self.retry_interval.value():
            commands.append(
                (
                    "AccountRetrySet",
                    {
                        "name": name,
                        "NUM": str(self.retry_num.value()),
                        "INTERVAL": str(self.retry_interval.value()),
                    },
                )
            )


def _yes(value: bool) -> str:
    return "yes" if value else "no"
