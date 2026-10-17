"""Headless smoke test: the real main window must build and function.

Run with:  QT_QPA_PLATFORM=offscreen python3 tests/smoke_gui.py
Requires PySide6; skipped automatically when it is not installed.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> int:
    from src.gui import theme
    from src.gui.editor import ButtonEditorDialog
    from src.gui.main_window import MainWindow
    from src.gui.settings import SettingsDialog
    from src.models import sanitize_action
    from src.profiles import ProfileStore

    app = QApplication([])
    theme.apply_theme(app)

    with tempfile.TemporaryDirectory() as tmp:
        store = ProfileStore(Path(tmp) / "abno-deck")
        store.load()
        window = MainWindow(store, auto_connect=False)
        window.show()
        app.processEvents()

        # 1. deck widgets mirror the profile
        assert window._deck.deck_button(1).button_config()["name"]
        # 2. trigger every slot with its (safe) default actions
        for slot in range(1, 5):
            window.trigger_slot(slot, "test")
            app.processEvents()
        # wait for the pool tasks to finish
        deadline = time.time() + 5
        while window._pool.activeThreadCount() and time.time() < deadline:
            time.sleep(0.05)
            app.processEvents()

        # 3. editor dialog opens, validates and produces a result
        editor = ButtonEditorDialog(window._store.button(2), 2, window)
        editor._shortcut.setText("Ctrl+Alt+T")
        editor._type.setCurrentIndex(3)
        editor._refresh_preview()
        assert sanitize_action(editor.current_action())["type"] == "media"
        editor._type.setCurrentIndex(2)
        editor._shortcut.setText("Ctrl+Alt+T")
        editor._on_accept()
        assert editor.result_button() is not None
        assert editor.result_button()["action"]["keys"] == "Ctrl+Alt+T"
        editor.close()

        # 4. invalid edits are rejected
        editor2 = ButtonEditorDialog(window._store.button(1), 1, window)
        editor2._url.setText("gopher://nope")
        editor2._type.setCurrentIndex(1)
        editor2._on_accept()
        assert editor2.result_button() is None, "invalid URL must be rejected"
        editor2.close()

        # 5. settings dialog loads
        settings = SettingsDialog(store, window)
        settings.close()

        # 6. serial manager: start, observe connecting state, stop cleanly
        window._serial.start("/dev/definitely-not-real-abno-deck")
        app.processEvents()
        time.sleep(0.4)
        app.processEvents()
        window._serial.stop()
        app.processEvents()

        # 7. profile CRUD through the store keeps the deck consistent
        pid = store.create_profile("Smoke")
        store.set_active(pid)
        window.refresh_profile_ui()
        app.processEvents()
        assert store.active_profile_id == pid

        # 8. logging bridge must be thread safe (worker thread -> GUI panel)
        import logging
        import threading as _threading

        from src.logsetup import QtLogHandler

        handler = QtLogHandler()
        handler.bridge.record.connect(
            lambda level, message: window._log(level, message, from_logger=True),
            Qt.QueuedConnection,
        )
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.INFO)
        panel_before = window._log_panel.blockCount()
        _threading.Thread(
            target=lambda: logging.getLogger("smoke").info("from a worker thread"),
            daemon=True,
        ).start()
        deadline = time.time() + 3
        while window._log_panel.blockCount() <= panel_before and time.time() < deadline:
            time.sleep(0.02)
            app.processEvents()
        assert window._log_panel.blockCount() > panel_before, \
            "log records from worker threads must reach the GUI panel"
        root_logger.removeHandler(handler)

        window.close()
        app.processEvents()

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
