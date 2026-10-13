"""Virtual network adapter management."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..dbus_client import MonitorSnapshot
from ..models import Nic


class NicPage(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._nics: list[Nic] = []

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nombre", "Estado", "MAC", "Versión"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        toolbar = QHBoxLayout()
        for label, slot in (
            ("Crear", self._create),
            ("Eliminar", self._delete),
            ("Habilitar", lambda: self._simple("NicEnable")),
            ("Deshabilitar", lambda: self._simple("NicDisable")),
            ("Cambiar MAC", self._set_mac),
            ("Actualizar", self.controller.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def update_snapshot(self, snapshot: MonitorSnapshot) -> None:
        self._nics = snapshot.nics
        self.table.setRowCount(len(self._nics))
        for row, nic in enumerate(self._nics):
            for column, value in enumerate([nic.name, nic.status, nic.mac, nic.version]):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)

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
            self.controller.refresh()

        self.controller.schedule(self.controller.client.run_client(command, args), on_done=_done)

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, "Nuevo adaptador", "Nombre:")
        if ok and name.strip():
            self._run("Crear adaptador", "NicCreate", {"name": name.strip()})

    def _delete(self) -> None:
        name = self._selected()
        if not name:
            return
        answer = QMessageBox.question(
            self, "Eliminar adaptador", f"¿Eliminar el adaptador '{name}'?"
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run("Eliminar adaptador", "NicDelete", {"name": name})

    def _simple(self, command: str) -> None:
        name = self._selected()
        if name:
            self._run(command, command, {"name": name})

    def _set_mac(self) -> None:
        name = self._selected()
        if not name:
            return
        mac, ok = QInputDialog.getText(
            self, "Cambiar MAC", "Dirección MAC (AA:BB:CC:DD:EE:FF):", QLineEdit.EchoMode.Normal
        )
        if ok and mac.strip():
            self._run("Cambiar MAC", "NicSetSetting", {"name": name, "MAC": mac.strip()})
