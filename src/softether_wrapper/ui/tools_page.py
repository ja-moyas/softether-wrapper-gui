"""Tools page: environment check, version info and MakeCert helper."""

from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..vpncmd_parser import parse_check


class ToolsPage(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller

        check_button = QPushButton("Comprobar entorno")
        check_button.clicked.connect(self._check)
        about_button = QPushButton("Acerca de vpncmd")
        about_button.clicked.connect(self._about)
        version_button = QPushButton("Versión del cliente")
        version_button.clicked.connect(self._version)
        tools_row = QHBoxLayout()
        tools_row.addWidget(check_button)
        tools_row.addWidget(about_button)
        tools_row.addWidget(version_button)
        tools_row.addStretch(1)
        tools_box = QGroupBox("Diagnóstico")
        tools_box.setLayout(tools_row)

        self.cn = QLineEdit("SoftEther")
        self.organization = QLineEdit("none")
        self.ou = QLineEdit("none")
        self.country = QLineEdit("none")
        self.state = QLineEdit("none")
        self.locality = QLineEdit("none")
        self.serial = QLineEdit("none")
        self.expires = QLineEdit("365")
        self.save_cert = QLineEdit()
        self.save_key = QLineEdit()

        form = QFormLayout()
        form.addRow("CN:", self.cn)
        form.addRow("O:", self.organization)
        form.addRow("OU:", self.ou)
        form.addRow("C:", self.country)
        form.addRow("ST:", self.state)
        form.addRow("L:", self.locality)
        form.addRow("Serial:", self.serial)
        form.addRow("Expira (días):", self.expires)
        form.addRow("Guardar certificado:", self.save_cert)
        form.addRow("Guardar clave:", self.save_key)
        create = QPushButton("Crear certificado")
        create.clicked.connect(self._make_cert)
        form.addRow(create)
        cert_box = QGroupBox("Crear certificado X.509")
        cert_box.setLayout(form)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        font = QFont("monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        self.output.setFont(font)

        layout = QVBoxLayout(self)
        layout.addWidget(tools_box)
        layout.addWidget(cert_box)
        layout.addWidget(QLabel("Salida:"))
        layout.addWidget(self.output, 1)

    def _show(self, text: str) -> None:
        self.output.setPlainText(text)

    def _run_tools(self, command: str, args: dict[str, str]) -> None:
        self.controller.schedule(
            self.controller.client.run_tools(command, args),
            on_done=lambda outcome: self._show(outcome.stdout or outcome.stderr),
            on_error=lambda exc: self._show(str(exc)),
        )

    def _check(self) -> None:
        def _done(outcome) -> None:
            result = parse_check(outcome.stdout)
            lines = []
            for item in result.items:
                status = "OK" if item.passed else "FALLO"
                detail = f": {item.message}" if item.message else ""
                lines.append(f"[{status}] {item.label}{detail}")
            if result.summary:
                lines.append("")
                lines.append(result.summary)
            if not lines:
                lines = [outcome.stdout or outcome.stderr]
            self._show("\n".join(lines))

        self.controller.schedule(self.controller.client.run_tools("Check", {}), on_done=_done)

    def _about(self) -> None:
        self._run_tools("About", {})

    def _version(self) -> None:
        self.controller.schedule(
            self.controller.client.run_client("VersionGet", {}),
            on_done=lambda outcome: self._show(outcome.stdout or outcome.stderr),
        )

    def _make_cert(self) -> None:
        args: dict[str, str] = {
            "CN": self.cn.text().strip() or "none",
            "O": self.organization.text().strip() or "none",
            "OU": self.ou.text().strip() or "none",
            "C": self.country.text().strip() or "none",
            "ST": self.state.text().strip() or "none",
            "L": self.locality.text().strip() or "none",
            "SERIAL": self.serial.text().strip() or "none",
            "EXPIRES": self.expires.text().strip() or "365",
        }
        if not self.save_cert.text().strip() or not self.save_key.text().strip():
            self._show("Indica rutas para el certificado y la clave (dentro de tu HOME).")
            return
        args["SAVECERT"] = self.save_cert.text().strip()
        args["SAVEKEY"] = self.save_key.text().strip()
        self._run_tools("MakeCert", args)
