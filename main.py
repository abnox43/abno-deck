#!/usr/bin/env python3
"""ABNO DECK - a DIY 4-key stream deck for Linux + ESP32.

Entry point: parses command line options, boots logging, loads the profile
store and starts the PySide6 main window.

Usage examples::

    ./main.py                       # normal start (auto-connects the ESP32)
    ./main.py --no-serial           # GUI only, do not open a serial port
    ./main.py --port /dev/ttyUSB0   # force a specific port
    ./main.py --profile default     # open a specific profile
    ./main.py --doctor              # print an environment report and exit
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Make the package importable no matter how the script is started.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from src.constants import APP_NAME, CONFIG_ENV_VAR, VERSION  # noqa: E402


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="abno-deck",
        description=f"{APP_NAME} {VERSION} - DIY stream deck controller for an ESP32 on Linux",
    )
    parser.add_argument("--config-dir", help="override the configuration directory "
                                             f"(default: ~/.config/abno-deck, env {CONFIG_ENV_VAR})")
    parser.add_argument("--profile", help="open the profile with this name or id")
    parser.add_argument("--port", help="serial port to use (default: auto-detect)")
    parser.add_argument("--no-serial", action="store_true",
                        help="do not open a serial port (GUI only)")
    parser.add_argument("--log-level", default=None,
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="console log level (the file log is always DEBUG)")
    parser.add_argument("--doctor", action="store_true",
                        help="print a report about the current environment and exit")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    return parser.parse_args(argv)


def run_doctor(config_dir: Path) -> int:
    """Headless environment report (also handy in bug reports)."""
    from src.deps import all_dependencies, missing_dependency_report, session_type
    from src.ports import detect_ports
    from src.profiles import ProfileStore

    print(f"{APP_NAME} {VERSION} - environment report")
    print(f"  python         : {sys.version.split()[0]} ({sys.executable})")
    print(f"  session type   : {session_type()}")
    print(f"  config dir     : {config_dir}")

    try:
        import PySide6

        print(f"  PySide6        : {PySide6.__version__}")
    except ImportError:
        print("  PySide6        : MISSING (sudo apt install python3-pyside6.qtwidgets)")
    try:
        import serial

        print(f"  pyserial       : {serial.VERSION}")
    except ImportError:
        print("  pyserial       : MISSING (sudo apt install python3-pyserial)")

    print("  dependencies   :")
    for dep in all_dependencies():
        state = dep.path if dep.found else f"MISSING - {dep.hint}"
        print(f"    {dep.label:<10}: {state}  ({dep.purpose})")

    ports = detect_ports()
    print(f"  serial ports   : {len(ports)} found")
    for info in ports:
        marker = " (ESP32 candidate)" if info.candidate else ""
        print(f"    {info.label()}{marker}")

    store = ProfileStore(config_dir)
    warnings = store.load()
    print(f"  profiles       : {len(store)} ({', '.join(name for _, name in store.list_profiles())})")
    for warning in warnings:
        print(f"    warning: {warning}")

    problems = missing_dependency_report()
    if problems:
        print("  recommendations:")
        for problem in problems:
            print(f"    - {problem}")
    print("report complete")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.config_dir:
        os.environ[CONFIG_ENV_VAR] = str(Path(args.config_dir).expanduser())

    from src.profiles import default_config_dir

    config_dir = default_config_dir()

    if args.doctor:
        return run_doctor(config_dir)

    from src.logsetup import setup_logging
    from src.profiles import ProfileError, ProfileStore

    setup_logging(config_dir, level=args.log_level or "INFO")
    log = logging.getLogger(__name__)

    store = ProfileStore(config_dir)
    store.load()
    if args.port is not None:
        store.settings["serial"]["port"] = args.port
    if args.profile:
        pid = store.find_profile_by_name(args.profile) or args.profile
        if pid in store.profiles:
            store.set_active(pid)
        else:
            log.warning("profile %r not found - using %r", args.profile,
                        store.active_profile.get("name"))

    # Import Qt only when we really start the GUI (keeps --doctor fast).
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from src.gui import theme
    from src.gui.main_window import MainWindow
    from src.gui.widgets import LogPanel  # noqa: F401  (ensures Qt widgets import)
    from src.logsetup import QtLogHandler

    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(VERSION)
    application.setDesktopFileName("abno-deck")
    theme.apply_theme(application)

    window = MainWindow(store, auto_connect=not args.no_serial)
    handler = QtLogHandler()
    # Explicit QueuedConnection: records produced by the serial worker are
    # delivered on the GUI thread - GUI widgets are never touched from the
    # worker thread (that crashes Qt).
    handler.bridge.record.connect(
        lambda level, message: window._log(level, message, from_logger=True),
        Qt.QueuedConnection,
    )
    logging.getLogger().addHandler(handler)
    window.show()
    log.info("GUI started")
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
