"""Dialog for configuring one stream-deck button."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import ACTION_TYPES, MEDIA_COMMANDS, MEDIA_LABELS
from ..desktop_entries import to_exec_fields
from ..models import describe_action, sanitize_action, sanitize_button, validate_action
from . import theme
from .app_picker import AppPickerDialog

log = logging.getLogger(__name__)

ACTION_LABELS = {
    "launch_app": "Launch an application",
    "open_url": "Open a website",
    "shortcut": "Send a keyboard shortcut",
    "media": "Control media playback",
    "command": "Run a custom command",
    "none": "Do nothing",
}

PRESET_EMOJI = [
    "🖥️", "🌐", "⏯️", "⏭️", "⏮️", "📁", "📸", "🔊", "🔇", "🎮",
    "📝", "🐧", "📧", "📅", "🔒", "🚀", "🛠️", "⭐", "🔥", "🧪",
    "📦", "🎬", "🎙️", "☕", "🗂️", "🖱️", "💾", "🔑", "💡", "⚡",
]


class ButtonEditorDialog(QDialog):
    """Edit name, icon and action of a single button.

    ``test_requested`` is emitted with a *sanitised* action dict when the user
    presses "Test"; the main window runs it through the normal dispatcher.
    """

    test_requested = Signal(object)

    def __init__(self, button: dict, slot: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Configure key {slot}")
        self.setMinimumWidth(620)
        self._slot = slot
        self._result: dict | None = None
        self._button = sanitize_button(button, slot=slot)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        header = QLabel(f"KEY {slot}  ·  ABNO DECK")
        header.setStyleSheet(f"color: {theme.SILVER}; font-size: 13px; font-weight: 700;")
        root.addWidget(header)

        # --- identity -------------------------------------------------------
        identity_box = QWidget()
        identity = QFormLayout(identity_box)
        identity.setContentsMargins(0, 0, 0, 0)

        self._name = QLineEdit(self._button["name"])
        self._name.setMaxLength(60)
        self._name.setPlaceholderText("Button name (e.g. Terminal)")

        icon_row = QWidget()
        icon_layout = QHBoxLayout(icon_row)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(4)
        self._icon = QLineEdit(self._button["icon"])
        self._icon.setMaxLength(8)
        self._icon.setMaximumWidth(90)
        self._icon.setPlaceholderText("emoji")
        icon_layout.addWidget(self._icon)
        for emoji in PRESET_EMOJI[:14]:
            chip = QPushButton(emoji)
            chip.setFixedSize(28, 26)
            chip.clicked.connect(lambda _checked=False, value=emoji: self._icon.setText(value))
            icon_layout.addWidget(chip)
        icon_layout.addStretch(1)

        identity.addRow("Name", self._name)
        identity.addRow("Icon", icon_row)
        root.addWidget(identity_box)

        # --- action type ----------------------------------------------------
        self._type = QComboBox()
        for key in ACTION_TYPES:
            self._type.addItem(ACTION_LABELS[key], key)
        self._type.currentIndexChanged.connect(self._on_type_changed)
        form = QFormLayout()
        form.addRow("Action", self._type)
        root.addLayout(form)

        # --- stacked detail editors ----------------------------------------
        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._launch_exe = QLineEdit()
        self._launch_args = QLineEdit()
        self._launch_exe.setPlaceholderText("executable, e.g. x-terminal-emulator")
        self._launch_args.setPlaceholderText('optional arguments, e.g. --new-tab "https://x"')
        self._launch_page = self._form_page(
            [
                ("Executable", self._launch_exe),
                ("Arguments", self._launch_args),
            ],
            "Full desktop entries are resolved without a shell; the program must "
            "exist in PATH or as an absolute path.",
        )
        self._pick_button = QPushButton("Browse installed applications…")
        self._pick_button.setObjectName("GhostButton")
        self._pick_button.clicked.connect(self._pick_application)
        self._form_of(self._launch_page).addRow("", self._pick_button)
        self._stack.addWidget(self._launch_page)

        self._url = QLineEdit()
        self._url.setPlaceholderText("https://example.org")
        self._url_page = self._form_page(
            [("URL", self._url)],
            "Only http:// and https:// URLs are handed to the default browser.",
        )
        self._stack.addWidget(self._url_page)

        self._shortcut = QLineEdit()
        self._shortcut.setPlaceholderText("Ctrl+Alt+T")
        self._shortcut_page = self._form_page(
            [("Shortcut", self._shortcut)],
            "Modifiers: Ctrl, Alt, Shift, Super — plus a key (a-z, 0-9, F1-F12, "
            "Return, space, arrows…). X11 uses xdotool, Wayland uses wtype/ydotool.",
        )
        self._stack.addWidget(self._shortcut_page)

        self._media = QComboBox()
        for key in MEDIA_COMMANDS:
            self._media.addItem(MEDIA_LABELS[key], key)
        self._media_page = self._form_page(
            [("Media command", self._media)],
            "Requires playerctl (or an MPRIS player reachable via dbus-send). "
            "If no player is running the press reports an error.",
        )
        self._stack.addWidget(self._media_page)

        self._command = QLineEdit()
        self._command.setPlaceholderText("command to run, e.g. playerctl play-pause")
        self._command_shell = QCheckBox("Allow shell interpretation (| & ; > < $ …)")
        self._command_shell.setToolTip(
            "Only enable this if the command really needs shell syntax. "
            "Without it, the command is executed directly as an argument list."
        )
        self._command_confirm = QCheckBox("Ask for confirmation before running")
        self._command_confirm.setChecked(True)
        warning = QLabel(
            "⚠ WARNING: custom commands run with your own user privileges. "
            "Only save commands you have read and understand."
        )
        warning.setProperty("role", "warning")
        warning.setWordWrap(True)
        self._command_page = self._form_page(
            [("Command", self._command)],
            "Validated before saving; executed without a shell unless the option below is set.",
        )
        command_form = self._form_of(self._command_page)
        command_form.addRow("", self._command_shell)
        command_form.addRow("", self._command_confirm)
        command_form.addRow("", warning)
        self._stack.addWidget(self._command_page)

        self._none_label = QLabel(
            "This button stays idle. You can still rename it or give it an icon."
        )
        self._none_label.setProperty("role", "hint")
        self._none_label.setWordWrap(True)
        self._none_page = QWidget()
        none_layout = QVBoxLayout(self._none_page)
        none_layout.setContentsMargins(0, 0, 0, 0)
        none_layout.addWidget(self._none_label)
        self._stack.addWidget(self._none_page)

        # --- live preview / validation -------------------------------------
        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet(f"color: {theme.ACCENT};")
        root.addWidget(self._preview)

        self._errors = QLabel()
        self._errors.setProperty("role", "error")
        self._errors.setWordWrap(True)
        root.addWidget(self._errors)
        root.addStretch(1)

        # --- dialog buttons --------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults
        )
        buttons.button(QDialogButtonBox.Save).setText("Save")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        buttons.button(QDialogButtonBox.RestoreDefaults).setText("Reset this key")
        buttons.button(QDialogButtonBox.RestoreDefaults).setObjectName("DangerButton")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self._on_extra_button)
        root.addWidget(buttons)

        # wire change signals for live validation
        for widget in (self._name, self._icon, self._launch_exe, self._launch_args,
                       self._url, self._shortcut, self._command):
            widget.textChanged.connect(self._refresh_preview)
        self._media.currentIndexChanged.connect(self._refresh_preview)
        self._command_shell.toggled.connect(self._refresh_preview)
        self._command_confirm.toggled.connect(self._refresh_preview)

        self._load_into_form()
        self._refresh_preview()

    # -- helpers ------------------------------------------------------------
    def _form_page(self, rows: list[tuple[str, QWidget]], hint: str = "") -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        for label, widget in rows:
            form.addRow(label, widget)
        layout.addLayout(form)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setProperty("role", "hint")
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)
        return page

    @staticmethod
    def _form_of(page: QWidget) -> QFormLayout:
        return page.layout().itemAt(0).layout()  # type: ignore[return-value]

    def _on_type_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._refresh_preview()

    def _pick_application(self) -> None:
        dialog = AppPickerDialog(self)
        if dialog.exec() and dialog.selected is not None:
            executable, arguments = to_exec_fields(dialog.selected.argv)
            self._launch_exe.setText(executable)
            self._launch_args.setText(arguments)
            if not self._name.text().strip() or self._name.text().startswith("Button "):
                self._name.setText(dialog.selected.name)

    def _load_into_form(self) -> None:
        action = sanitize_action(self._button.get("action"))
        self._name.setText(self._button["name"])
        self._icon.setText(self._button["icon"])
        index = ACTION_TYPES.index(action["type"])
        self._type.setCurrentIndex(index)
        if action["type"] == "launch_app":
            self._launch_exe.setText(action.get("executable", ""))
            self._launch_args.setText(action.get("arguments", ""))
        elif action["type"] == "open_url":
            self._url.setText(action.get("url", ""))
        elif action["type"] == "shortcut":
            self._shortcut.setText(action.get("keys", ""))
        elif action["type"] == "media":
            position = MEDIA_COMMANDS.index(action["command"])
            self._media.setCurrentIndex(position)
        elif action["type"] == "command":
            self._command.setText(action.get("command", ""))
            self._command_shell.setChecked(bool(action.get("use_shell")))
            self._command_confirm.setChecked(bool(action.get("confirm", True)))
        self._on_type_changed(self._type.currentIndex())

    def current_action(self) -> dict:
        kind = self._type.currentData()
        action: dict = {"type": kind}
        if kind == "launch_app":
            action["executable"] = self._launch_exe.text().strip()
            action["arguments"] = self._launch_args.text().strip()
        elif kind == "open_url":
            action["url"] = self._url.text().strip()
        elif kind == "shortcut":
            action["keys"] = self._shortcut.text().strip()
        elif kind == "media":
            action["command"] = self._media.currentData()
        elif kind == "command":
            action["command"] = self._command.text().strip()
            action["use_shell"] = self._command_shell.isChecked()
            action["confirm"] = self._command_confirm.isChecked()
        return sanitize_action(action)

    def _refresh_preview(self) -> None:
        action = self.current_action()
        self._preview.setText(f"▶ {describe_action(action)}")
        problems = validate_action(action)
        name = self._name.text().strip()
        if not name:
            problems.append("button name must not be empty")
        if not self._icon.text().strip():
            problems.append("button icon must not be empty")
        self._errors.setText("\n".join(problems))
        self._errors.setVisible(bool(problems))

    def _on_accept(self) -> None:
        action = self.current_action()
        problems = validate_action(action)
        name = self._name.text().strip()
        if not name:
            problems.append("button name must not be empty")
        icon = self._icon.text().strip()
        if not icon:
            problems.append("button icon must not be empty")
        if problems:
            self._refresh_preview()
            self._errors.setFocus()
            return
        self._result = sanitize_button(
            {"slot": self._slot, "name": name, "icon": icon, "action": action},
            slot=self._slot,
        )
        self.accept()

    def _on_extra_button(self, button) -> None:
        if button.text() == "Reset this key":
            from ..models import new_button

            self._button = new_button(self._slot)
            self._load_into_form()
            self._refresh_preview()

    # -- results ------------------------------------------------------------
    def result_button(self) -> dict | None:
        return self._result

    def unsaved_action(self) -> dict:
        return self.current_action()


__all__ = ["ButtonEditorDialog"]
