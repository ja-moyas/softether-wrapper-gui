"""Accounts page: list, create, edit, delete, connect and import/export."""

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
from ..models import AccountSummary, Nic
from ..vpncmd_parser import parse_account_get
from .account_dialog import AccountDialog

Command = tuple[str, dict[str, str]]


class AccountsPage(QWidget):
    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._accounts: list[AccountSummary] = []
        self._nics: list[Nic] = []

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Nombre", "Estado", "Servidor", "Hub", "Adaptador"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        toolbar = QHBoxLayout()
        for label, slot in (
            ("Nueva", self._new),
            ("Editar", self._edit),
            ("Eliminar", self._delete),
            ("Conectar", self._connect),
            ("Desconectar", self._disconnect),
            ("Exportar", self._export),
            ("Importar", self._import),
            ("Actualizar", self.controller.refresh),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    # -- data --------------------------------------------------------------
    def update_snapshot(self, snapshot: MonitorSnapshot) -> None:
        self._accounts = snapshot.accounts
        self._nics = snapshot.nics
        self.table.setRowCount(len(self._accounts))
        for row, account in enumerate(self._accounts):
            values = [account.name, account.status, account.server, account.hub, account.nic]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)

    def selected_account(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return item.text() if item else None

    # -- actions -----------------------------------------------------------
    def _run_commands(self, title: str, commands: list[Command]) -> None:
        if not commands:
            return

        def _done(outcomes) -> None:
            failed = [o for o in outcomes if o.exit_code != 0]
            if failed:
                self.controller.notify(
                    title,
                    failed[0].error_message or f"código {failed[0].exit_code}",
                    error=True,
                )
            self.controller.refresh()

        self.controller.schedule(self.controller.client.run_client_batch(commands), on_done=_done)

    def _new(self) -> None:
        dialog = AccountDialog(nics=self._nics, parent=self)
        if dialog.exec() == AccountDialog.DialogCode.Accepted:
            try:
                commands = dialog.build_commands()
            except ValueError as exc:
                QMessageBox.warning(self, "Cuenta", str(exc))
                return
            self._run_commands("Nueva cuenta", commands)

    def _edit(self) -> None:
        name = self.selected_account()
        if not name:
            return

        def _got(outcome) -> None:
            if outcome.exit_code != 0:
                self.controller.notify("Editar", outcome.error_message, error=True)
                return
            detail = parse_account_get(outcome.stdout)
            dialog = AccountDialog(nics=self._nics, detail=detail, parent=self)
            if dialog.exec() == AccountDialog.DialogCode.Accepted:
                try:
                    commands = dialog.build_commands()
                except ValueError as exc:
                    QMessageBox.warning(self, "Cuenta", str(exc))
                    return
                self._run_commands("Editar cuenta", commands)

        self.controller.schedule(
            self.controller.client.run_client("AccountGet", {"name": name}), on_done=_got
        )

    def _delete(self) -> None:
        name = self.selected_account()
        if not name:
            return
        answer = QMessageBox.question(
            self,
            "Eliminar cuenta",
            f"¿Eliminar la cuenta '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_commands("Eliminar cuenta", [("AccountDelete", {"name": name})])

    def _connect(self) -> None:
        name = self.selected_account()
        if name:
            self.controller.connect_account(name)

    def _disconnect(self) -> None:
        name = self.selected_account()
        if name:
            self.controller.disconnect_account(name)

    def _export(self) -> None:
        name = self.selected_account()
        if not name:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Exportar cuenta", str(Path.home() / f"{name}.vpn"), "VPN (*.vpn)"
        )
        if path:
            self._run_commands("Exportar cuenta", [("AccountExport", {"name": name, "SAVEPATH": path})])

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importar cuenta", str(Path.home()))
        if path:
            self._run_commands("Importar cuenta", [("AccountImport", {"path": path})])
