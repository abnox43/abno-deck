"""End-to-end test of the serial layer against a fake ESP32 on a pty.

A pseudo-terminal plays the role of the microcontroller: the "firmware" side
writes the protocol lines, ABNO DECK opens the other end exactly like a real
USB serial port.  This exercises port opening, handshake, parsing, debouncing,
malformed input handling and clean shutdown for real - no mocking of pyserial.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import unittest

try:
    import pty
    from PySide6.QtCore import QCoreApplication
    from src.serial_io import (
        STATE_CONNECTED,
        STATE_CONNECTING,
        STATE_DISCONNECTED,
        SerialManager,
    )
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def wait_for(condition, timeout: float = 6.0, step: float = 0.02) -> bool:
    """Pump the Qt event loop until ``condition()`` is true."""
    app = QCoreApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if condition():
            return True
        time.sleep(step)
    return False


@unittest.skipUnless(HAVE_QT, "PySide6 is required for the serial integration test")
class SerialManagerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        self.master_fd, self.slave_fd = pty.openpty()
        self.port = os.ttyname(self.slave_fd)
        self.manager = SerialManager(debounce_ms=250)
        self.states: list[str] = []
        self.buttons: list[int] = []
        self.ready_count = 0
        self.malformed: list[str] = []
        self.errors: list[str] = []
        self.logs: list[tuple[str, str]] = []
        self.manager.stateChanged.connect(self.states.append)
        self.manager.buttonPressed.connect(self.buttons.append)
        self.manager.malformedReceived.connect(lambda raw, reason: self.malformed.append(raw))
        self.manager.errorOccurred.connect(lambda message, hint: self.errors.append(message))
        self.manager.logged.connect(lambda level, message: self.logs.append((level, message)))

        def on_ready():
            self.ready_count += 1

        self.manager.readyReceived.connect(on_ready)

    def tearDown(self):
        self.manager.stop()
        for fd in (self.master_fd, self.slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def _firmware_reset_then_presses(self, presses: list[bytes]) -> None:
        """Simulate a resetting ESP32: handshake, then deliberate presses."""
        def run():
            time.sleep(0.35)  # give the desktop time to open the port
            os.write(self.master_fd, b"ABNODECK:READY\n")
            time.sleep(0.9)   # real users press after the reset settles
            for line in presses:
                os.write(self.master_fd, line)
                time.sleep(0.05)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def test_handshake_buttons_debounce_and_malformed_input(self):
        self._firmware_reset_then_presses([
            b"BUTTON:1\n",
            b"BUTTON:1\r\n",        # duplicate within the debounce window
            b"BUTTON:9\n",          # out of range
            b"BANNER:whatever\n",   # unknown line
            b"BUTTON:1; rm -rf /\n",  # malformed / hostile
            b"BUTTON:3\n",
        ])

        self.manager.start(self.port)
        self.assertTrue(wait_for(lambda: self.ready_count >= 1), f"no handshake; logs={self.logs}")
        self.assertTrue(wait_for(lambda: 3 in self.buttons),
                        f"buttons={self.buttons} errors={self.errors}")
        # allow the trailing duplicates to arrive before asserting
        wait_for(lambda: len(self.malformed) >= 3, timeout=1.0)
        time.sleep(0.4)
        self.app.processEvents()

        self.assertEqual(self.ready_count, 1)
        self.assertEqual(self.buttons.count(1), 1, "debounce must suppress the duplicate")
        self.assertIn(3, self.buttons)
        self.assertNotIn(9, self.buttons, "out-of-range buttons must be dropped")
        self.assertTrue(set(self.buttons) <= {1, 3},
                        f"only valid, debounced buttons may reach the GUI: {self.buttons}")
        self.assertIn(STATE_CONNECTED, self.states)

        self.manager.stop()
        self.assertEqual(self.manager.state, STATE_DISCONNECTED)
        self.assertTrue(wait_for(lambda: STATE_DISCONNECTED in self.states),
                        f"states={self.states}")

    def test_missing_port_reports_error_and_state_changes(self):
        self.manager.start("/dev/abno-deck-nonexistent-port")
        self.assertTrue(wait_for(lambda: len(self.errors) >= 1),
                        "opening a missing port must report an error")
        self.assertIn(STATE_CONNECTING, self.states)
        self.manager.stop()
        self.assertEqual(self.manager.state, STATE_DISCONNECTED)

    def test_stop_releases_port_for_reopening(self):
        self.manager.start(self.port)
        self.assertTrue(wait_for(lambda: self.manager.is_running))
        self.manager.stop()
        # the same port must be openable again immediately (guard released)
        import serial

        handle = serial.Serial(self.port, 115200, timeout=0.2, exclusive=True)
        self.assertTrue(handle.is_open)
        handle.close()

    def test_configure_restarts_on_port_change(self):
        self.manager.start(self.port)
        self.assertTrue(wait_for(lambda: self.manager.is_running))
        self.manager.configure(port="/dev/abno-deck-other")
        self.assertTrue(wait_for(lambda: self.manager.target_port == "/dev/abno-deck-other"))
        wait_for(lambda: self.manager.is_running, timeout=3.0)

    def test_repeated_identical_errors_are_emitted_once(self):
        received: list[str] = []
        self.manager.errorOccurred.connect(lambda message, hint: received.append(message))
        self.manager.emit_error("permission denied for /dev/ttyUSB0", "hint")
        self.manager.emit_error("permission denied for /dev/ttyUSB0", "hint")
        self.manager.emit_error("permission denied for /dev/ttyUSB0", "hint")
        self.assertEqual(len(received), 1, "reconnect spam must be de-duplicated")
        self.manager.emit_error("device is busy", "")
        self.assertEqual(len(received), 2)


if __name__ == "__main__":
    unittest.main()
