"""The 2x2 stream-deck preview: one interactive widget per physical button."""

from __future__ import annotations

import os

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer, QEasingCurve, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..constants import NUM_BUTTONS
from ..models import describe_action, sanitize_button
from . import theme


class DeckButton(QFrame):
    """One virtual stream-deck key.

    * left click executes the action (test run),
    * the gear button opens the configuration editor,
    * :meth:`flash` gives visual feedback for physical presses.
    """

    clicked = Signal()

    def __init__(self, slot: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.slot = slot
        self.setObjectName("DeckButton")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(150, 130)
        self._button: dict = sanitize_button({}, slot=slot)
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(180)
        self._flash_timer.timeout.connect(self._end_flash)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)

        top_row = QWidget()
        top_layout = QGridLayout(top_row)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self._slot_label = QLabel(f"KEY {slot}")
        self._slot_label.setObjectName("DeckSlot")
        self._gear = QToolButton()
        self._gear.setText("⚙")
        self._gear.setToolTip("Configure this button")
        self._gear.setFixedSize(24, 24)
        top_layout.addWidget(self._slot_label, 0, 0, alignment=Qt.AlignLeft)
        top_layout.addWidget(self._gear, 0, 1, alignment=Qt.AlignRight)
        layout.addWidget(top_row)

        layout.addStretch(1)
        self._icon_label = QLabel()
        self._icon_label.setObjectName("DeckIcon")
        self._icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon_label, alignment=Qt.AlignCenter)

        self._name_label = QLabel()
        self._name_label.setObjectName("DeckName")
        self._name_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._name_label)

        self._action_label = QLabel()
        self._action_label.setObjectName("DeckAction")
        self._action_label.setAlignment(Qt.AlignCenter)
        self._action_label.setWordWrap(True)
        layout.addWidget(self._action_label)
        layout.addStretch(1)

        self._icon_effect = QGraphicsOpacityEffect(self._icon_label)
        self._icon_effect.setOpacity(1.0)
        self._icon_label.setGraphicsEffect(self._icon_effect)
        self._icon_animation = QPropertyAnimation(self._icon_effect, b"opacity", self)
        self._icon_animation.setDuration(180)
        self._icon_animation.setEasingCurve(QEasingCurve.OutCubic)

    # -- data ---------------------------------------------------------------
    def set_button(self, button: dict) -> None:
        self._button = sanitize_button(button, slot=self.slot)
        self._name_label.setText(self._button["name"])
        self._action_label.setText(describe_action(self._button["action"]))
        self.setToolTip(
            f"Key {self.slot}: {self._button['name']}\n"
            f"{describe_action(self._button['action'])}\n"
            "Left click: run · ⚙: configure"
        )
        self._set_icon(self._button["icon"])

    def button_config(self) -> dict:
        return self._button

    def _set_icon(self, icon: str) -> None:
        icon = (icon or "").strip()
        if icon and os.path.isfile(icon):
            pixmap = QPixmap(icon)
            if not pixmap.isNull():
                self._icon_label.setPixmap(
                    pixmap.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                )
                return
        font = QFont(self._icon_label.font())
        font.setPointSizeF(30)
        self._icon_label.setFont(font)
        self._icon_label.setText(icon or "⬜")

    # -- interaction --------------------------------------------------------
    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if event.button() == Qt.LeftButton:
            self.press_feedback()
            self.clicked.emit()
            return
        super().mousePressEvent(event)

    def press_feedback(self) -> None:
        """Short phosphor flash - cheap, no repaint storms."""
        self._icon_animation.stop()
        self._icon_animation.setStartValue(1.0)
        self._icon_animation.setEndValue(0.25)
        self._icon_animation.start()
        QTimer.singleShot(90, self._bounce)
        self._flash_timer.start()

    def _bounce(self) -> None:
        self._icon_animation.stop()
        self._icon_animation.setStartValue(0.25)
        self._icon_animation.setEndValue(1.0)
        self._icon_animation.start()

    def _end_flash(self) -> None:
        self.update()

    # -- gear button wiring --------------------------------------------------
    @property
    def gear_button(self) -> QToolButton:
        return self._gear


class _Scanlines(QWidget):
    """Transparent overlay drawing subtle CRT scanlines over the deck."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        pen = QPen(QColor(0, 0, 0, 26))
        pen.setWidth(1)
        painter.setPen(pen)
        y = 0
        while y < self.height():
            painter.drawLine(0, y, self.width(), y)
            y += 3
        painter.end()


class DeckFrame(QWidget):
    """2x2 grid of :class:`DeckButton` plus the CRT overlay."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buttons: dict[int, DeckButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)

        self._surface = QFrame()
        self._surface.setObjectName("Panel")
        grid = QGridLayout(self._surface)
        grid.setContentsMargins(14, 14, 14, 14)
        grid.setSpacing(14)
        for index in range(NUM_BUTTONS):
            slot = index + 1
            deck_button = DeckButton(slot)
            grid.addWidget(deck_button, index // 2, index % 2)
            self._buttons[slot] = deck_button
        outer.addWidget(self._surface)

        self._scanlines = _Scanlines(self._surface)

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        self._scanlines.setGeometry(self._surface.rect())

    # -- API ----------------------------------------------------------------
    def deck_button(self, slot: int) -> DeckButton:
        return self._buttons[slot]

    def update_button(self, slot: int, button: dict) -> None:
        self._buttons[slot].set_button(button)

    def flash(self, slot: int) -> None:
        button = self._buttons.get(slot)
        if button is not None:
            button.press_feedback()

    def set_active_slot(self, slot: int | None) -> None:
        for number, button in self._buttons.items():
            button.setProperty("active", "true" if number == slot else "false")
            button.style().unpolish(button)
            button.style().polish(button)


__all__ = ["DeckButton", "DeckFrame"]
