"""Searchable application picker built from Linux ``.desktop`` entries."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..desktop_entries import AppEntry, load_desktop_entries

log = logging.getLogger(__name__)


class AppPickerDialog(QDialog):
    """Pick an installed program; returns an :class:`AppEntry` or ``None``."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pick an application")
        self.setMinimumSize(560, 480)
        self._entries: list[AppEntry] = []
        self.selected: AppEntry | None = None

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Applications were read from ~/.local/share/applications and "
            "/usr/share/applications. Type to filter by name, keyword or command."
        )
        intro.setWordWrap(True)
        intro.setProperty("role", "hint")
        layout.addWidget(intro)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search applications… (e.g. terminal, firefox, editor)")
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)

        self._status = QLabel(" ")
        self._status.setProperty("role", "hint")
        layout.addWidget(self._status)

        self._list = QListWidget()
        self._list.setIconSize(self._list.iconSize())
        layout.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Select")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancel")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._search.textChanged.connect(self._apply_filter)
        self._list.itemDoubleClicked.connect(self._accept_selection)
        self._list.currentItemChanged.connect(lambda *_: self._update_status())
        self._search.returnPressed.connect(self._select_first)

        # Load after the dialog is visible so the UI paints immediately.
        QTimer.singleShot(30, self._load_entries)

    # -- data ---------------------------------------------------------------
    def _load_entries(self) -> None:
        self._status.setText("Loading desktop entries…")
        QApplication_process_events()
        try:
            self._entries = load_desktop_entries()
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("desktop entry scan failed: %s", exc)
            self._entries = []
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str) -> None:
        needle = (text or "").strip()
        self._list.clear()
        matches = [entry for entry in self._entries if entry.matches(needle)]
        for entry in matches[:400]:
            item = QListWidgetItem(QIcon.fromTheme(entry.icon), entry.name)
            detail = entry.comment or entry.exec_line
            item.setToolTip(f"{entry.name}\n{detail}\n\nExec: {' '.join(entry.argv)}")
            item.setData(Qt.UserRole, entry)
            self._list.addItem(item)
        if self._list.count():
            self._list.setCurrentRow(0)
        self._update_status()

    def _update_status(self) -> None:
        total = len(self._entries)
        shown = self._list.count()
        if not total:
            self._status.setText(
                "No desktop entries found — install applications normally, "
                "or close this dialog and type an executable name in the editor."
            )
        else:
            self._status.setText(f"Showing {shown} of {total} applications")

    # -- selection ----------------------------------------------------------
    def _select_first(self) -> None:
        if self._list.count():
            self._list.setCurrentRow(0)
            self._accept_selection()

    def _accept_selection(self, *_args) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        if isinstance(entry, AppEntry):
            self.selected = entry
            self.accept()


def QApplication_process_events() -> None:  # tiny helper, keeps import local
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()


__all__ = ["AppPickerDialog"]
