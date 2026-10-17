"""Reusable GUI widgets: connection indicator and the event log panel."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QRectF, Qt, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QVBoxLayout, QLabel, QWidget

from ..constants import APP_NAME
from . import theme

STATE_LABELS = {
    "disconnected": "DISCONNECTED",
    "connecting": "CONNECTING",
    "connected": "CONNECTED",
}
STATE_COLORS = {
    "disconnected": QColor(theme.ERR),
    "connecting": QColor(theme.WARN),
    "connected": QColor(theme.OK),
}


class ConnectionIndicator(QWidget):
    """Pulsing status dot + label for the serial link."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "disconnected"
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.25)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(700)
        self._animation.setEasingCurve(QEasingCurve.InOutSine)
        self._animation.setLoopCount(-1)
        self._animation.valueChanged.connect(self._on_frame)
        self.setFixedHeight(22)

    # -- API ----------------------------------------------------------------
    def set_state(self, state: str) -> None:
        if state not in STATE_LABELS:
            state = "disconnected"
        self._state = state
        if state == "connecting":
            if self._animation.state() != QVariantAnimation.Running:
                self._animation.start()
        else:
            self._animation.stop()
            self._animation.setCurrentTime(0)
        self.setToolTip(f"{APP_NAME}: serial link {STATE_LABELS[state].lower()}")
        self.update()

    @property
    def state(self) -> str:
        return self._state

    def text(self) -> str:
        return STATE_LABELS[self._state]

    # -- painting -----------------------------------------------------------
    def _on_frame(self, _value) -> None:
        self.update()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(150, 22)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        alpha = 1.0
        if self._state == "connecting":
            alpha = float(self._animation.currentValue())
        color = QColor(STATE_COLORS[self._state])
        color.setAlphaF(max(0.2, alpha))

        center_y = self.height() / 2
        radius = 5.0
        # soft glow ring
        glow = QColor(color)
        glow.setAlphaF(0.18 * max(0.2, alpha))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(6 - radius * 1.9, center_y - radius * 1.9,
                                   radius * 3.8, radius * 3.8))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(6 - radius, center_y - radius, radius * 2, radius * 2))

        painter.setPen(QPen(QColor(theme.SILVER)))
        font = QFont(painter.font())
        font.setPointSizeF(9.5)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(20, 0, self.width() - 20, self.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, self.text())
        painter.end()


class LogPanel(QPlainTextEdit):
    """Timestamped, colour coded event log with a bounded line count."""

    MAX_LINES = 600

    _LEVEL_COLORS = {
        "debug": theme.TEXT_DIM,
        "info": theme.TEXT,
        "press": theme.ACCENT,
        "action": theme.ACCENT,
        "warning": theme.WARN,
        "error": theme.ERR,
        "success": theme.OK,
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogPanel")
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setPlaceholderText(f"{APP_NAME} event log — physical presses, actions and errors appear here")

    def append_entry(self, level: str, message: str, timestamp: datetime | None = None) -> None:
        level = (level or "info").lower()
        colour = self._LEVEL_COLORS.get(level, theme.TEXT)
        stamp = (timestamp or datetime.now()).strftime("%H:%M:%S")
        safe_message = (
            message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        self.appendHtml(
            f'<span style="color:{theme.TEXT_DIM}">{stamp}</span> '
            f'<span style="color:{colour}; font-weight:600">{level.upper():<7}</span> '
            f'<span style="color:{colour}">{safe_message}</span>'
        )
        # keep the newest entry visible
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def clear_entries(self) -> None:
        self.clear()


def make_section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setProperty("role", "hint")
    font = label.font()
    font.setPointSizeF(8.5)
    font.setBold(True)
    label.setFont(font)
    return label


__all__ = ["ConnectionIndicator", "LogPanel", "STATE_LABELS", "make_section_title"]
