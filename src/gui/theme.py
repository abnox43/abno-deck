"""Dark cyberpunk / CRT visual theme for ABNO DECK.

A single stylesheet plus a few colour constants, so the whole look stays
coherent and easy to tweak.  The CRT flavour comes from a scanline overlay on
the deck frame and phosphor-tinted accents - no heavy graphics effects, so it
stays smooth even on modest hardware.
"""

from __future__ import annotations

# palette ------------------------------------------------------------------
BG = "#0a0d12"
BG_ALT = "#0e131a"
PANEL = "#121821"
PANEL_LIGHT = "#182130"
PANEL_DARK = "#0c1118"
BORDER = "#263241"
BORDER_LIGHT = "#33445a"
SILVER = "#c8cfd8"
SILVER_DIM = "#8a94a3"
TEXT = "#d7dee8"
TEXT_DIM = "#7d8896"
ACCENT = "#2ee6d6"      # phosphor cyan
ACCENT_DIM = "#1a8f88"
ACCENT2 = "#ff3d81"     # neon magenta
OK = "#4ade80"
WARN = "#fbbf24"
ERR = "#f87171"

MONO_STACK = '"JetBrains Mono", "DejaVu Sans Mono", "Ubuntu Mono", monospace'

STYLE_SHEET = f"""
* {{
    font-family: {MONO_STACK};
    font-size: 12px;
    color: {TEXT};
}}
QWidget#MainWindow {{
    background-color: {BG};
}}
QFrame#TopBar, QFrame#BottomBar {{
    background-color: {BG_ALT};
    border-top: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
}}
QLabel#AppTitle {{
    font-size: 19px;
    font-weight: 700;
    color: {SILVER};
    letter-spacing: 3px;
    padding: 4px 2px;
}}
QLabel#AppTitleAccent {{
    font-size: 19px;
    font-weight: 700;
    color: {ACCENT};
    letter-spacing: 3px;
}}
QLabel#AppSubtitle {{
    font-size: 10px;
    color: {TEXT_DIM};
    letter-spacing: 2px;
}}
QFrame#Panel {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QLabel#SectionTitle {{
    font-size: 11px;
    font-weight: 700;
    color: {SILVER_DIM};
    letter-spacing: 2px;
}}
QLabel[role="hint"] {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
QLabel[role="error"] {{
    color: {ERR};
    font-size: 11px;
}}
QLabel[role="warning"] {{
    color: {WARN};
    font-size: 11px;
}}
QLabel[role="ok"] {{
    color: {OK};
    font-size: 11px;
}}

/* ---- deck buttons ---- */
QFrame#DeckButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 {PANEL_LIGHT}, stop:1 {PANEL_DARK});
    border: 1px solid {BORDER_LIGHT};
    border-radius: 10px;
}}
QFrame#DeckButton:hover {{
    border: 1px solid {ACCENT_DIM};
}}
QFrame#DeckButton[active="true"] {{
    border: 1px solid {ACCENT};
}}
QLabel#DeckSlot {{
    color: {TEXT_DIM};
    font-size: 10px;
    letter-spacing: 1px;
}}
QLabel#DeckIcon {{
    font-size: 34px;
}}
QLabel#DeckName {{
    color: {SILVER};
    font-size: 13px;
    font-weight: 700;
}}
QLabel#DeckAction {{
    color: {TEXT_DIM};
    font-size: 10px;
}}

/* ---- log panel ---- */
QPlainTextEdit#LogPanel {{
    background-color: {PANEL_DARK};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {ACCENT_DIM};
    font-size: 11px;
}}

/* ---- standard controls ---- */
QPushButton {{
    background-color: {PANEL_LIGHT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 6px 12px;
    color: {TEXT};
}}
QPushButton:hover {{
    border: 1px solid {ACCENT_DIM};
    background-color: #1d2839;
}}
QPushButton:pressed {{
    background-color: {PANEL_DARK};
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    background-color: {PANEL_DARK};
}}
QPushButton#AccentButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                      stop:0 #173a3d, stop:1 #10262b);
    border: 1px solid {ACCENT_DIM};
    color: {ACCENT};
    font-weight: 700;
}}
QPushButton#AccentButton:hover {{
    border: 1px solid {ACCENT};
}}
QPushButton#DangerButton {{
    border: 1px solid #6d2733;
    color: {ERR};
}}
QPushButton#DangerButton:hover {{
    border: 1px solid {ERR};
    background-color: #2a151b;
}}
QPushButton#GhostButton {{
    background-color: transparent;
    border: 1px solid {BORDER};
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    padding: 3px;
    color: {SILVER_DIM};
}}
QToolButton:hover {{
    border: 1px solid {ACCENT_DIM};
    color: {ACCENT};
}}
QComboBox {{
    background-color: {PANEL_LIGHT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 5px 10px;
    min-height: 20px;
}}
QComboBox:hover {{
    border: 1px solid {ACCENT_DIM};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background-color: {PANEL};
    border: 1px solid {BORDER_LIGHT};
    selection-background-color: #173a3d;
    selection-color: {ACCENT};
    outline: none;
}}
QLineEdit, QSpinBox, QPlainTextEdit {{
    background-color: {PANEL_DARK};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1px solid {ACCENT_DIM};
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {BORDER_LIGHT};
    border-radius: 3px;
    background-color: {PANEL_DARK};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT_DIM};
    border: 1px solid {ACCENT};
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 8px;
    font-weight: 700;
    color: {SILVER_DIM};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    background-color: {PANEL};
    top: -1px;
}}
QTabBar::tab {{
    background-color: {PANEL_DARK};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 6px 14px;
    margin-right: 3px;
    color: {TEXT_DIM};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border: 1px solid {ACCENT_DIM};
}}
QListWidget {{
    background-color: {PANEL_DARK};
    border: 1px solid {BORDER};
    border-radius: 6px;
    outline: none;
}}
QListWidget::item {{
    padding: 5px 6px;
    border-radius: 4px;
}}
QListWidget::item:selected {{
    background-color: #173a3d;
    color: {ACCENT};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 9px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_LIGHT};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 9px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_LIGHT};
    border-radius: 4px;
    min-width: 24px;
}}
QStatusBar {{
    background-color: {BG_ALT};
    border-top: 1px solid {BORDER};
    color: {TEXT_DIM};
}}
QToolTip {{
    background-color: {PANEL};
    color: {TEXT};
    border: 1px solid {BORDER_LIGHT};
    padding: 4px;
}}
QMessageBox {{
    background-color: {PANEL};
}}
QSplitter::handle {{
    background-color: {BORDER};
    width: 2px;
}}
"""


def apply_theme(application) -> None:
    """Install the stylesheet on a ``QApplication`` instance."""
    application.setStyle("Fusion")
    application.setStyleSheet(STYLE_SHEET)


__all__ = [
    "ACCENT", "ACCENT2", "ACCENT_DIM", "apply_theme", "BG", "BG_ALT", "BORDER",
    "ERR", "MONO_STACK", "OK", "PANEL", "PANEL_DARK", "PANEL_LIGHT", "SILVER",
    "SILVER_DIM", "STYLE_SHEET", "TEXT", "TEXT_DIM", "WARN",
]
