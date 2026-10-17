"""Main window of ABNO DECK."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import actions
from ..constants import APP_NAME, NUM_BUTTONS, VERSION
from ..deps import missing_dependency_report, session_type
from ..models import describe_action
from ..profiles import ProfileError, ProfileStore
from ..serial_io import (
    STATE_CONNECTED,
    STATE_CONNECTING,
    STATE_DISCONNECTED,
    SerialManager,
    list_ports_for_ui,
)
from . import theme
from .deck import DeckFrame
from .editor import ButtonEditorDialog
from .settings import SettingsDialog
from .widgets import ConnectionIndicator, LogPanel

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# background action execution (keeps the GUI thread free)
# --------------------------------------------------------------------------
class _ActionSignals(QObject):
    finished = Signal(object)


class ActionTask(QRunnable):
    def __init__(self, action: dict, callback) -> None:
        super().__init__()
        self._action = action
        self._signals = _ActionSignals()
        self._signals.finished.connect(callback)
        self.setAutoDelete(True)

    def run(self) -> None:  # executed on a pool thread
        result = actions.execute(self._action)
        self._signals.finished.emit(result)


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, store: ProfileStore, *, auto_connect: bool = True,
                 start_port: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.setMinimumSize(900, 600)

        self._store = store
        self._pool = QThreadPool.globalInstance()
        self._serial = SerialManager(
            debounce_ms=int(store.settings["serial"].get("debounce_ms", 250)), parent=self
        )

        self._build_ui()
        self._wire_serial()

        # restore window size
        window = store.settings.get("window", {})
        self.resize(int(window.get("width", 1080)), int(window.get("height", 720)))

        self._log("info", f"{APP_NAME} {VERSION} ready — session type: {session_type()}")
        for warning in store.warnings:
            self._log("warning", warning)
        for warning in missing_dependency_report():
            self._log("warning", warning)
            self._status_label.setToolTip(self._status_label.toolTip() + "\n" + warning)
        self.refresh_profile_ui()

        serial_settings = store.settings["serial"]
        self._apply_serial_settings(serial_settings)
        if auto_connect and serial_settings.get("auto_connect", True):
            self._serial.start(serial_settings.get("port", ""))
        else:
            self._log("info", "Automatic connection is disabled - press Connect to start")

    # ------------------------------------------------------------------ UI --
    def _build_ui(self) -> None:
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(12, 10, 12, 6)
        central_layout.setSpacing(10)

        # --- top bar -------------------------------------------------------
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(14, 8, 14, 8)
        top_layout.setSpacing(10)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setSpacing(0)
        title_a = QLabel(APP_NAME.split()[0])
        title_a.setObjectName("AppTitle")
        title_b = QLabel(" " + " ".join(APP_NAME.split()[1:]))
        title_b.setObjectName("AppTitleAccent")
        title_row.addWidget(title_a)
        title_row.addWidget(title_b)
        subtitle = QLabel("DIY STREAM DECK · ESP32 · LINUX")
        subtitle.setObjectName("AppSubtitle")
        title_box.addLayout(title_row)
        title_box.addWidget(subtitle)
        top_layout.addLayout(title_box)
        top_layout.addStretch(1)

        profile_label = QLabel("PROFILE")
        profile_label.setObjectName("DeckSlot")
        top_layout.addWidget(profile_label)
        self._profile_combo = QComboBox()
        self._profile_combo.setMinimumWidth(170)
        self._profile_combo.currentIndexChanged.connect(self._on_profile_selected)
        top_layout.addWidget(self._profile_combo)

        for text, slot, slot_name, danger in (
            ("＋", 0, "New profile", False),
            ("✎", 1, "Rename profile", False),
            ("⧉", 2, "Duplicate profile", False),
            ("🗑", 3, "Delete profile", True),
        ):
            tool = QToolButton()
            tool.setText(text)
            tool.setToolTip(slot_name)
            tool.setFixedSize(26, 26)
            if danger:
                tool.setObjectName("DangerButton")
            tool.clicked.connect(self._make_profile_button_handler(slot))
            top_layout.addWidget(tool)

        top_layout.addSpacing(12)

        self._indicator = ConnectionIndicator()
        top_layout.addWidget(self._indicator)

        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(190)
        self._port_combo.setToolTip("Serial port (auto-detect or manual selection)")
        self._port_combo.currentIndexChanged.connect(self._on_port_changed)
        top_layout.addWidget(self._port_combo)

        self._connect_button = QPushButton("Disconnect")
        self._connect_button.setObjectName("AccentButton")
        self._connect_button.clicked.connect(self._toggle_connection)
        top_layout.addWidget(self._connect_button)

        settings_button = QToolButton()
        settings_button.setText("⚙")
        settings_button.setToolTip("Settings")
        settings_button.setFixedSize(26, 26)
        settings_button.clicked.connect(self._open_settings)
        top_layout.addWidget(settings_button)

        central_layout.addWidget(top_bar)

        # --- deck + log ----------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)
        self._deck = DeckFrame()
        splitter.addWidget(self._deck)

        log_wrapper = QFrame()
        log_wrapper.setObjectName("Panel")
        log_layout = QVBoxLayout(log_wrapper)
        log_layout.setContentsMargins(10, 10, 10, 10)
        log_title = QLabel("EVENT LOG")
        log_title.setObjectName("SectionTitle")
        log_layout.addWidget(log_title)
        self._log_panel = LogPanel()
        log_layout.addWidget(self._log_panel)
        splitter.addWidget(log_wrapper)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 420])
        central_layout.addWidget(splitter, 1)

        self.setCentralWidget(central)

        # --- status bar -----------------------------------------------------
        status = QStatusBar()
        self._status_label = QLabel(
            f"Config: {self._store.config_dir}  ·  changes are saved automatically"
        )
        self._status_label.setStyleSheet(f"color: {theme.TEXT_DIM};")
        status.addWidget(self._status_label)
        self.setStatusBar(status)

        # deck button wiring
        for slot in range(1, NUM_BUTTONS + 1):
            deck_button = self._deck.deck_button(slot)
            deck_button.clicked.connect(lambda checked=False, s=slot: self.trigger_slot(s, "virtual"))
            deck_button.gear_button.clicked.connect(lambda checked=False, s=slot: self._edit_slot(s))

    def _make_profile_button_handler(self, action_id: int):
        return lambda checked=False: {
            0: self._new_profile,
            1: self._rename_profile,
            2: self._duplicate_profile,
            3: self._delete_profile,
        }[action_id]()

    # -------------------------------------------------------------- serial --
    def _wire_serial(self) -> None:
        self._serial.stateChanged.connect(self._on_state_changed)
        self._serial.buttonPressed.connect(self._on_physical_press)
        # NOTE: SerialManager.logged is intentionally NOT connected here - those
        # messages already go through the logging module and reach the log panel
        # via QtLogHandler, so connecting them again would duplicate every line.
        self._serial.errorOccurred.connect(self._on_serial_error)
        self._serial.malformedReceived.connect(self._on_malformed)
        self._serial.readyReceived.connect(
            lambda: self._log("success", "ESP32 handshake complete")
        )

    def _apply_serial_settings(self, serial_settings: dict) -> None:
        self._serial.configure(
            port=serial_settings.get("port", ""),
            baud=int(serial_settings.get("baud_rate", 115200)),
            debounce_ms=int(serial_settings.get("debounce_ms", 250)),
            auto_reconnect=bool(serial_settings.get("auto_reconnect", True)),
        )

    def _refresh_port_combo(self) -> None:
        current = self._store.settings["serial"].get("port", "")
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        for device, label in list_ports_for_ui():
            self._port_combo.addItem(label, device)
        index = self._port_combo.findData(current)
        self._port_combo.setCurrentIndex(index if index >= 0 else 0)
        self._port_combo.blockSignals(False)

    def _on_port_changed(self, index: int) -> None:
        if index < 0:
            return
        device = self._port_combo.itemData(index) or ""
        if device == self._store.settings["serial"].get("port", ""):
            return
        self._store.update_settings(serial={"port": device})
        self._serial.configure(port=device)
        self._log("info", f"Serial port set to {device or 'auto-detect'}")
        if self._serial.is_running:
            self._serial.stop()
            self._serial.start()

    def _toggle_connection(self) -> None:
        if self._serial.is_running:
            self._serial.stop()
            self._log("info", "Disconnected by user")
        else:
            self._serial.start(self._store.settings["serial"].get("port", ""))

    def _on_state_changed(self, state: str) -> None:
        self._indicator.set_state(state)
        if state == STATE_CONNECTED:
            port = self._serial.target_port or "auto-detected port"
            self._connect_button.setText("Disconnect")
            self._status_label.setText(f"Connected to {port} @ {self._serial.baud_rate} baud")
        elif state == STATE_CONNECTING:
            self._connect_button.setText("Cancel")
        else:
            self._connect_button.setText("Connect")
            self._status_label.setText(
                f"Config: {self._store.config_dir}  ·  changes are saved automatically"
            )

    def _on_serial_error(self, message: str, hint: str) -> None:
        # The SerialManager already logged this record; only mirror it into the
        # panel (from_logger=True prevents duplicates in the log file).
        self._log("error", message, from_logger=True)
        if hint:
            for line in hint.splitlines():
                self._log("warning", line, from_logger=True)
            self._status_label.setToolTip(hint)

    def _on_malformed(self, raw: str, reason: str) -> None:
        self._log("warning", f"Serial input ignored: {raw!r} ({reason})",
                  from_logger=True)

    def _on_physical_press(self, slot: int) -> None:
        self._log("press", f"Physical key {slot} pressed")
        self.trigger_slot(slot, "physical")

    # ------------------------------------------------------------- actions --
    def trigger_slot(self, slot: int, source: str = "virtual") -> None:
        """Execute the action assigned to a button (from GUI or ESP32)."""
        try:
            button = self._store.button(slot)
        except ProfileError as exc:
            self._log("error", str(exc))
            return

        action = button.get("action", {"type": "none"})
        self._deck.flash(slot)
        self._deck.set_active_slot(slot)
        self._log(
            "action",
            f"{source.capitalize()} key {slot} → {button['name']}: {describe_action(action)}",
        )

        if action.get("type") == "command" and action.get("confirm", True):
            answer = QMessageBox.question(
                self,
                "Confirm command",
                f"Key {slot} wants to run a custom command:\n\n"
                f"    {action.get('command', '')}\n\n"
                f"Shell interpretation: {'yes' if action.get('use_shell') else 'no'}\n\n"
                "Run it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self._log("info", f"Command for key {slot} cancelled by user")
                return

        self._pool.start(ActionTask(action, self._on_action_finished))

    @Slot(object)
    def _on_action_finished(self, result) -> None:
        if result.ok:
            self._log("success", f"OK: {result.log_line()}"
                      + (f" [{result.backend}]" if result.backend else ""))
        else:
            self._log("error", f"FAILED: {result.log_line()}")
        for warning in result.warnings:
            self._log("warning", warning)

    def _edit_slot(self, slot: int) -> None:
        current = self._store.button(slot)
        dialog = ButtonEditorDialog(current, slot, self)
        dialog.test_requested.connect(
            lambda action: self._run_test_action(action, slot)
        )
        if dialog.exec() != QDialog_Accepted:
            return
        result = dialog.result_button()
        if result is None:
            return
        try:
            self._store.set_button(slot, result)
        except ProfileError as exc:
            self._log("error", f"Could not save key {slot}: {exc}")
            QMessageBox.critical(self, "Save failed", str(exc))
            return
        self._deck.update_button(slot, result)
        self._log("info", f"Key {slot} saved: {describe_action(result['action'])}")

    def _run_test_action(self, action: dict, slot: int) -> None:
        """Test an (unsaved) action from the editor dialog."""
        from ..models import sanitize_action

        clean = sanitize_action(action)
        if clean.get("type") == "command" and clean.get("confirm", True):
            answer = QMessageBox.question(
                self,
                "Confirm test",
                f"Run this command for testing?\n\n    {clean.get('command', '')}\n",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        self._log("action", f"Testing key {slot}: {describe_action(clean)}")
        self._pool.start(ActionTask(clean, self._on_action_finished))

    # ------------------------------------------------------------ profiles --
    def refresh_profile_ui(self) -> None:
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        active = self._store.active_profile_id
        for pid, name in self._store.list_profiles():
            self._profile_combo.addItem(name, pid)
        index = self._profile_combo.findData(active)
        if index >= 0:
            self._profile_combo.setCurrentIndex(index)
        self._profile_combo.blockSignals(False)
        self._refresh_deck()
        self._refresh_port_combo()

    def _refresh_deck(self) -> None:
        try:
            profile = self._store.active_profile
        except ProfileError as exc:
            self._log("error", str(exc))
            return
        self.setWindowTitle(f"{APP_NAME} {VERSION} — {profile['name']}")
        for button in profile["buttons"]:
            self._deck.update_button(button["slot"], button)

    def _on_profile_selected(self, index: int) -> None:
        if index < 0:
            return
        pid = self._profile_combo.itemData(index)
        if not pid or pid == self._store.active_profile_id:
            return
        try:
            self._store.set_active(pid)
        except ProfileError as exc:
            self._log("error", str(exc))
            return
        self._refresh_deck()
        self._log("info", f"Switched to profile '{self._store.active_profile['name']}'")

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New profile", "Profile name:")
        if not ok or not str(name).strip():
            return
        try:
            pid = self._store.create_profile(str(name).strip())
        except (ProfileError, OSError) as exc:
            self._log("error", f"Could not create profile: {exc}")
            return
        self.refresh_profile_ui()
        index = self._profile_combo.findData(pid)
        if index >= 0:
            self._profile_combo.setCurrentIndex(index)
        self._log("info", f"Created profile '{self._store.get(pid)['name']}'")

    def _rename_profile(self) -> None:
        profile = self._store.active_profile
        name, ok = QInputDialog.getText(
            self, "Rename profile", "Profile name:", text=profile["name"]
        )
        if not ok or not str(name).strip():
            return
        try:
            self._store.rename_profile(profile["id"], str(name).strip())
        except ProfileError as exc:
            self._log("error", str(exc))
            return
        self.refresh_profile_ui()
        self._log("info", f"Profile renamed to '{profile['name']}'")

    def _duplicate_profile(self) -> None:
        profile = self._store.active_profile
        try:
            pid = self._store.duplicate_profile(profile["id"])
        except (ProfileError, OSError) as exc:
            self._log("error", str(exc))
            return
        self.refresh_profile_ui()
        index = self._profile_combo.findData(pid)
        if index >= 0:
            self._profile_combo.setCurrentIndex(index)
        self._log("info", f"Duplicated profile as '{self._store.get(pid)['name']}'")

    def _delete_profile(self) -> None:
        profile = self._store.active_profile
        if len(self._store) <= 1:
            QMessageBox.warning(self, "Delete profile",
                                "The last remaining profile cannot be deleted.")
            return
        answer = QMessageBox.question(
            self, "Delete profile",
            f"Delete profile '{profile['name']}' and all of its buttons?\n"
            "This removes the profile file from disk.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            self._store.delete_profile(profile["id"])
        except ProfileError as exc:
            self._log("error", str(exc))
            return
        self.refresh_profile_ui()
        self._log("info", f"Deleted profile '{profile['name']}'")

    # ------------------------------------------------------------- settings --
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._store, self)
        dialog.restart_serial_requested.connect(self._reload_from_disk)
        if dialog.exec() != QDialog_Accepted:
            return
        updates = dialog.result_updates()
        if not updates:
            return
        try:
            self._store.update_settings(**updates)
        except ProfileError as exc:
            self._log("error", f"Could not save settings: {exc}")
            return
        self._apply_serial_settings(self._store.settings["serial"])
        self._refresh_port_combo()
        self._log("info", "Settings applied")
        if self._serial.is_running:
            self._serial.stop()
            self._serial.start(self._store.settings["serial"].get("port", ""))

    def _reload_from_disk(self) -> None:
        """Profiles changed on disk (e.g. after a restore)."""
        for warning in self._store.load():
            self._log("warning", warning)
        self.refresh_profile_ui()

    # ---------------------------------------------------------------- misc --
    def _log(self, level: str, message: str, from_logger: bool = False) -> None:
        """Single funnel for the event log panel and the log file.

        ``from_logger=True`` marks messages that were already written to the
        log file by another module (e.g. the serial manager) - they are only
        mirrored into the panel, never logged twice.
        """
        if not from_logger:
            record_level = level if level in ("debug", "info", "warning", "error") else "info"
            getattr(log, record_level)(
                "%s", message, extra={"abno_gui_shown": True}
            )
        self._log_panel.append_entry("success" if level == "success" else level, message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt API)
        self._log("info", "Shutting down - releasing the serial port")
        try:
            self._store.update_settings(window={"width": self.width(), "height": self.height()})
        except ProfileError:
            pass
        self._serial.stop()
        event.accept()


# Qt's accept constant used when comparing dialog results
QDialog_Accepted = QDialog.Accepted

__all__ = ["MainWindow"]
