"""Settings dialog: serial link, environment status and backup/restore."""

from __future__ import annotations

import logging
import os
import subprocess
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..backup import BackupError, create_backup, restore_backup
from ..deps import all_dependencies, session_type
from ..ports import detect_ports
from ..profiles import ProfileStore
from . import theme
from .widgets import make_section_title

log = logging.getLogger(__name__)


class SettingsDialog(QDialog):
    """Edit application settings; returns nothing - changes are applied on OK."""

    restart_serial_requested = Signal()

    def __init__(self, store: ProfileStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ABNO DECK — Settings")
        self.setMinimumWidth(640)
        self._store = store
        self._result: dict | None = None

        root = QVBoxLayout(self)
        root.setSpacing(10)

        # --- serial ---------------------------------------------------------
        serial_box = QGroupBox("Serial connection (ESP32)")
        serial_form = QFormLayout(serial_box)

        self._port = QComboBox()
        self._refresh_ports()
        self._port_refresh = QPushButton("Refresh")
        self._port_refresh.setObjectName("GhostButton")
        self._port_refresh.clicked.connect(self._refresh_ports)
        port_row = QHBoxLayout()
        port_row.addWidget(self._port, 1)
        port_row.addWidget(self._port_refresh)
        serial_form.addRow("Port", port_row)

        self._baud = QComboBox()
        for baud in (115200, 230400, 57600, 9600):
            self._baud.addItem(str(baud), baud)
        serial_form.addRow("Baud rate", self._baud)

        self._auto_connect = QCheckBox("Connect automatically at startup")
        self._auto_reconnect = QCheckBox("Reconnect automatically after unplugging")
        serial_form.addRow("", self._auto_connect)
        serial_form.addRow("", self._auto_reconnect)

        self._debounce = QSpinBox()
        self._debounce.setRange(0, 5000)
        self._debounce.setSingleStep(50)
        self._debounce.setSuffix(" ms")
        serial_form.addRow("Debounce", self._debounce)

        hint = QLabel(
            "The port opens at the selected baud rate from a background thread, so the "
            "window never freezes. If opening fails, the log shows the exact permission "
            "fix (usually: sudo usermod -aG dialout \"$USER\" + re-login)."
        )
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        serial_form.addRow("", hint)
        root.addWidget(serial_box)

        # --- environment ----------------------------------------------------
        env_box = QGroupBox("Linux environment")
        env_layout = QVBoxLayout(env_box)
        self._env_table = QLabel()
        self._env_table.setWordWrap(True)
        self._env_table.setTextFormat(Qt.PlainText)
        env_layout.addWidget(self._env_table)
        root.addWidget(env_box)

        # --- backup ---------------------------------------------------------
        backup_box = QGroupBox("Configuration backup")
        backup_layout = QVBoxLayout(backup_box)
        row = QHBoxLayout()
        self._backup_button = QPushButton("Create backup…")
        self._backup_button.clicked.connect(self._do_backup)
        self._restore_button = QPushButton("Restore backup…")
        self._restore_button.clicked.connect(self._do_restore)
        self._open_dir_button = QPushButton("Open config folder")
        self._open_dir_button.setObjectName("GhostButton")
        self._open_dir_button.clicked.connect(self._open_config_dir)
        row.addWidget(self._backup_button)
        row.addWidget(self._restore_button)
        row.addWidget(self._open_dir_button)
        row.addStretch(1)
        backup_layout.addLayout(row)
        backup_hint = QLabel(
            f"Configuration directory: {self._store.config_dir}\n"
            "Backups are plain ZIP files containing profiles and settings. "
            "Restoring keeps a copy of the current configuration first."
        )
        backup_hint.setProperty("role", "hint")
        backup_hint.setWordWrap(True)
        backup_layout.addWidget(backup_hint)
        root.addWidget(backup_box)

        # --- dialog buttons --------------------------------------------------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load()

    # -- loading ------------------------------------------------------------
    def _refresh_ports(self) -> None:
        current = self._port.currentData() if self._port.count() else None
        self._port.clear()
        self._port.addItem("Auto-detect (recommended)", "")
        for info in detect_ports():
            self._port.addItem(info.label(), info.device)
        if current is not None:
            index = self._port.findData(current)
            if index >= 0:
                self._port.setCurrentIndex(index)

    def _load(self) -> None:
        serial = self._store.settings["serial"]
        index = self._port.findData(serial.get("port", ""))
        self._port.setCurrentIndex(index if index >= 0 else 0)
        baud_index = self._baud.findData(serial.get("baud_rate", 115200))
        self._baud.setCurrentIndex(baud_index if baud_index >= 0 else 0)
        self._auto_connect.setChecked(bool(serial.get("auto_connect", True)))
        self._auto_reconnect.setChecked(bool(serial.get("auto_reconnect", True)))
        self._debounce.setValue(int(serial.get("debounce_ms", 250)))
        self._env_table.setText(self._environment_text())

    @staticmethod
    def _environment_text() -> str:
        session = session_type()
        lines = [f"Session type: {session}"]
        if session == "wayland":
            lines.append(
                "Wayland detected: xdotool cannot inject keys here; install wtype "
                "or ydotool for keyboard shortcuts."
            )
        for dep in all_dependencies():
            if dep.key == "session":
                continue
            state = dep.path if dep.found else "MISSING"
            lines.append(f"• {dep.label:<10} {state:<38} {dep.purpose}")
            if not dep.found:
                lines.append(f"{'':14}→ install with: {dep.hint}")
        return "\n".join(lines)

    # -- actions ------------------------------------------------------------
    def _do_backup(self) -> None:
        default = Path.home() / "abno-deck-backup.zip"
        path, _ = QFileDialog.getSaveFileName(
            self, "Create ABNO DECK backup", str(default), "ZIP archives (*.zip)"
        )
        if not path:
            return
        try:
            archive = create_backup(self._store.config_dir, path)
        except BackupError as exc:
            QMessageBox.critical(self, "Backup failed", str(exc))
            return
        QMessageBox.information(self, "Backup created", f"Backup written to:\n{archive}")

    def _do_restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Restore ABNO DECK backup", str(Path.home()), "ZIP archives (*.zip)"
        )
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "Restore backup?",
            "Restoring replaces the current profiles and settings.\n"
            "A copy of the current configuration is kept automatically.\n\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            report = restore_backup(path, self._store.config_dir)
        except BackupError as exc:
            QMessageBox.critical(self, "Restore failed", str(exc))
            return
        text = report.summary()
        if report.pre_restore_copy:
            text += f"\n\nPrevious configuration kept at:\n{report.pre_restore_copy}"
        QMessageBox.information(self, "Restore complete", text)
        self.restart_serial_requested.emit()

    def _open_config_dir(self) -> None:
        path = str(self._store.config_dir)
        try:
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        except OSError:
            QMessageBox.information(self, "Configuration folder", path)

    def _on_accept(self) -> None:
        self._result = {
            "serial": {
                "port": self._port.currentData() or "",
                "baud_rate": self._baud.currentData(),
                "auto_connect": self._auto_connect.isChecked(),
                "auto_reconnect": self._auto_reconnect.isChecked(),
                "debounce_ms": self._debounce.value(),
            }
        }
        self.accept()

    def result_updates(self) -> dict | None:
        return self._result


__all__ = ["SettingsDialog"]
