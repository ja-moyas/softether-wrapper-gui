"""Preferences dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import Preferences


class SettingsDialog(QDialog):
    def __init__(
        self,
        prefs: Preferences,
        accounts: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferencias")
        self.setMinimumWidth(420)

        self.interval = QSpinBox()
        self.interval.setRange(1000, 60000)
        self.interval.setSingleStep(500)
        self.interval.setSuffix(" ms")
        self.interval.setValue(prefs.monitor_interval_ms)

        self.notifications = QCheckBox("Mostrar notificaciones de escritorio")
        self.notifications.setChecked(prefs.notifications)

        self.hide_on_close = QCheckBox("Ocultar en la bandeja al cerrar la ventana")
        self.hide_on_close.setChecked(prefs.hide_on_close)

        self.autostart = QCheckBox("Iniciar al iniciar sesión")
        self.autostart.setChecked(prefs.autostart)

        self.default_account = QComboBox()
        self.default_account.setEditable(True)
        self.default_account.addItem("")
        for name in accounts or []:
            self.default_account.addItem(name)
        self.default_account.setCurrentText(prefs.default_account)

        self.tap_interface = QLineEdit(prefs.tap_interface)
        self.show_ip = QCheckBox("Mostrar la dirección IP del adaptador")
        self.show_ip.setChecked(prefs.show_ip)

        form = QFormLayout()
        form.addRow("Intervalo de monitorización:", self.interval)
        form.addRow(self.notifications)
        form.addRow(self.hide_on_close)
        form.addRow(self.autostart)
        form.addRow("Cuenta por defecto:", self.default_account)
        form.addRow("Interfaz TAP:", self.tap_interface)
        form.addRow(self.show_ip)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_preferences(self, base: Preferences) -> Preferences:
        return Preferences(
            monitor_interval_ms=self.interval.value(),
            notifications=self.notifications.isChecked(),
            hide_on_close=self.hide_on_close.isChecked(),
            autostart=self.autostart.isChecked(),
            default_account=self.default_account.currentText().strip(),
            tap_interface=self.tap_interface.text().strip() or base.tap_interface,
            show_ip=self.show_ip.isChecked(),
            helper_retry_ms=base.helper_retry_ms,
        )
