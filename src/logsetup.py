"""Logging setup: rotating file in the config dir plus a Qt friendly hook."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .constants import APP_ID
from .profiles import default_config_dir

LOG_FILE_NAME = "abno-deck.log"


def setup_logging(config_dir: Path | None = None, level: str = "INFO") -> Path:
    """Configure root logging; returns the log file path."""
    directory = config_dir or default_config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / LOG_FILE_NAME

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )
    root.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    root.addHandler(console)

    logging.getLogger(__name__).debug("%s logging initialised (file=%s)", APP_ID, log_path)
    return log_path


class _GuiEmitter(QObject):
    """Thread-safe funnel: emitting a signal from any thread is safe, and the
    queued connection delivers it on the GUI thread."""

    record = Signal(str, str)  # level, formatted message


class QtLogHandler(logging.Handler):
    """Forward log records to the GUI log panel through a Qt signal bridge.

    * Never touches widgets directly - logging may happen on the serial worker
      thread, and GUI access from there crashes Qt.
    * Records that the GUI itself already displayed (marked with the
      ``abno_gui_shown`` extra field) are skipped, which breaks the
      logger -> GUI -> logger feedback loop.
    """

    ORIGIN_FLAG = "abno_gui_shown"

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self._emitter = _GuiEmitter()
        self.setFormatter(logging.Formatter("%(message)s"))

    @property
    def bridge(self) -> _GuiEmitter:
        """Connect ``bridge.record`` to the GUI slot (queued to its thread)."""
        return self._emitter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if getattr(record, self.ORIGIN_FLAG, False):
                return
            self._emitter.record.emit(record.levelname.lower(), self.format(record))
        except Exception:  # pragma: no cover - never break logging
            pass


__all__ = ["LOG_FILE_NAME", "QtLogHandler", "setup_logging"]
