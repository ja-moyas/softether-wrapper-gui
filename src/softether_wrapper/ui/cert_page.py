"""Trusted CA certificate list management."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..dbus_client import MonitorSnapshot
from ..models import Certificate


class CertPage(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._certs: list[Certificate] = []

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Identificador", "Detalles"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        toolbar = QHBoxLayout()
        for label, slot in (
            ("Añadir", self._add),
            ("Eliminar", self._delete),
            ("Guardar como…", self._get),
            ("Actualizar", self._refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def _refresh(self) -> None:
        def _done(outcome) -> None:
            from ..vpncmd_parser import parse_cert_list

            self._certs = parse_cert_list(outcome.stdout) if outcome.exit_code == 0 else []
            self.table.setRowCount(len(self._certs))
            for row, cert in enumerate(self._certs):
                for column, value in enumerate([cert.identifier, cert.label]):
                    item = QTableWidgetItem(value)
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.table.setItem(row, column, item)

        self.controller.schedule(
            self.controller.client.run_client("CertList", {}), on_done=_done
        )

    def update_snapshot(self, snapshot: MonitorSnapshot) -> None:  # noqa: ARG002
        pass

    def _selected(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    def _run(self, title: str, command: str, args: dict) -> None:
        def _done(outcome) -> None:
            if outcome.exit_code != 0:
                self.controller.notify(title, outcome.error_message, error=True)
            self._refresh()

        self.controller.schedule(self.controller.client.run_client(command, args), on_done=_done)

    def _add(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Añadir certificado", str(Path.home()))
        if path:
            self._run("Añadir certificado", "CertAdd", {"path": path})

    def _delete(self) -> None:
        identifier = self._selected()
        if not identifier:
            return
        answer = QMessageBox.question(
            self, "Eliminar certificado", f"¿Eliminar el certificado '{identifier}'?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run("Eliminar certificado", "CertDelete", {"id": identifier})

    def _get(self) -> None:
        identifier = self._selected()
        if not identifier:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar certificado", str(Path.home() / "certificate.cer"), "Certificado (*.cer *.crt *.pem)"
        )
        if path:
            self._run("Guardar certificado", "CertGet", {"id": identifier, "SAVECERT": path})
