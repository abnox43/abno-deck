"""Regression tests for two critical serial bugs.

Bug 1 - all four actions fire on startup:
    Opening the port toggles DTR/RTS and resets the ESP32.  Everything that
    arrives in the wake of that reset - kernel-buffered backlog, replayed
    state, boot pin glitches that pass a naive firmware debounce - is a burst
    of syntactically valid ``BUTTON:1..4`` lines.  The old code dispatched
    every validated line from the first byte onwards, so all four keys fired
    as soon as the app connected.

Bug 2 - physical buttons stop working afterwards:
    ``SerialWorker.run()`` had no try/finally.  Any unexpected exception in
    the read/dispatch path (``ValueError`` on a closed file, ``RuntimeError``
    from a deleted Qt object, a bug in a slot ...) killed the daemon thread
    silently and leaked the device claim in ``_OPEN_DEVICES``, so every later
    reconnect failed forever with "already open by ABNO DECK".

These tests drive a pseudo-terminal exactly like a resetting ESP32 would and
assert the *required* behaviour:
  * opening the app never executes button actions,
  * READY only updates connection status,
  * validated presses after the startup window dispatch exactly once,
  * the reader survives unexpected errors and reconnects.
"""

from __future__ import annotations

import os
import sys
import time
import unittest

try:
    import pty
    from PySide6.QtCore import QCoreApplication
    from src import serial_io
    from src.constants import STARTUP_IGNORE_GRACE
    from src.serial_io import (
        STATE_CONNECTED,
        SerialManager,
    )
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False


def wait_for(condition, timeout: float = 8.0, step: float = 0.02) -> bool:
    app = QCoreApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if condition():
            return True
        time.sleep(step)
    return False


BOOT_LOG = (
    b"ets Jul 29 2019 12:21:46 (build:7d3ad4ad)\r\n"
    b"\r\n"
    b"rst:0x1 (POWERON_RESET),boot:0x13 (SPI_FAST_FLASH_BOOT)\r\n"
    b"configsip: 0, SPIWP:0xee\r\n"
    b"mode:DIO, clock div:1\r\n"
    b"load:0x3fff0030,len:1184\r\n"
    b"load:0x40078000,len:13260\r\n"
    b"load:0x40080400,len:3028\r\n"
    b"entry 0x400805c4\r\n"
)

# What a resetting ESP32 emits right after the port opens: handshake plus a
# burst of boot-time "presses" (pin glitches / buffered replay).
RESET_BURST = (
    b"ABNODECK:READY\n"
    b"BUTTON:1\nBUTTON:2\nBUTTON:3\nBUTTON:4\n"
)


class _PtyTestCase(unittest.TestCase):
    def setUp(self):
        self.app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
        self.master_fd, self.slave_fd = pty.openpty()
        self.port = os.ttyname(self.slave_fd)
        self.manager = SerialManager(debounce_ms=250)
        self.buttons: list[int] = []
        self.ready = 0
        self.errors: list[str] = []
        self.manager.buttonPressed.connect(self.buttons.append)
        self.manager.errorOccurred.connect(lambda message, hint: self.errors.append(message))

        def on_ready():
            self.ready += 1

        self.manager.readyReceived.connect(on_ready)

    def tearDown(self):
        self.manager.stop()
        self.assertNotIn(self.port, serial_io._OPEN_DEVICES,
                         "device claim leaked - reconnects would fail forever")
        for fd in (self.master_fd, self.slave_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def wait_until_port_open(self, timeout: float = 6.0) -> None:
        """Wait until the worker really holds the port.

        Data written before the worker opens the port counts as stale input
        (and is discarded by design), so live traffic must start afterwards.
        """
        self.assertTrue(
            wait_for(lambda: self.port in serial_io._OPEN_DEVICES, timeout),
            f"port never opened; errors={self.errors}",
        )
        time.sleep(0.25)  # finish the stale-input flush before sending live data
        self.app.processEvents()

    def wait_until_operational(self) -> None:
        """Connected, and past the bounded startup window."""
        self.assertTrue(wait_for(lambda: self.manager.state == STATE_CONNECTED, 8.0),
                        f"never connected; errors={self.errors}")
        deadline = time.monotonic() + STARTUP_IGNORE_GRACE + 0.35
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)

    def start_and_wait_open(self) -> None:
        self.manager.start(self.port)
        self.wait_until_port_open()


@unittest.skipUnless(HAVE_QT, "PySide6 is required")
class StartupSafetyTests(_PtyTestCase):
    """Bug 1: opening the app must never execute button actions."""

    def test_reset_burst_at_connect_is_not_dispatched(self):
        """READY + BUTTON:1..4 arriving together (DTR reset) must not fire."""
        self.start_and_wait_open()
        os.write(self.master_fd, RESET_BURST)

        self.assertTrue(wait_for(lambda: self.ready == 1, 5.0),
                        f"handshake missing; errors={self.errors}")
        self.assertEqual(self.manager.state, STATE_CONNECTED)
        time.sleep(STARTUP_IGNORE_GRACE + 0.3)
        self.app.processEvents()
        self.assertEqual(self.buttons, [],
                         f"startup burst must not dispatch actions: {self.buttons}")

    def test_stale_buffered_presses_are_never_dispatched(self):
        # presses made while nothing was listening - they sit in the tty buffer
        os.write(self.master_fd, b"BUTTON:1\nBUTTON:2\nBUTTON:3\nBUTTON:4\n")
        # the previous session also died mid-line
        os.write(self.master_fd, b"BUTTON:")

        self.manager.start(self.port)
        self.wait_until_operational()
        self.assertEqual(self.buttons, [],
                         f"stale buffered presses must never dispatch: {self.buttons}")

        # ...but a *real* press after the startup window must still work
        os.write(self.master_fd, b"BUTTON:2\n")
        self.assertTrue(wait_for(lambda: 2 in self.buttons),
                        f"live press not dispatched; buttons={self.buttons}")

    def test_bootloader_text_is_ignored(self):
        self.start_and_wait_open()
        os.write(self.master_fd, BOOT_LOG)
        self.wait_until_operational()
        self.assertEqual(self.buttons, [], "bootloader text must not dispatch actions")

        os.write(self.master_fd, b"BUTTON:4\n")
        self.assertTrue(wait_for(lambda: 4 in self.buttons))
        self.assertEqual(self.buttons, [4])

    def test_ready_updates_status_only(self):
        self.start_and_wait_open()
        os.write(self.master_fd, b"ABNODECK:READY\n")
        self.assertTrue(wait_for(lambda: self.ready == 1, 5.0))
        self.assertEqual(self.manager.state, STATE_CONNECTED)
        time.sleep(STARTUP_IGNORE_GRACE + 0.3)
        self.app.processEvents()
        self.assertEqual(self.buttons, [], "READY must only update connection status")

    def test_each_real_press_dispatches_exactly_once(self):
        self.start_and_wait_open()
        os.write(self.master_fd, b"ABNODECK:READY\n")
        self.wait_until_operational()
        for _ in range(6):  # bouncing switch / firmware burst
            os.write(self.master_fd, b"BUTTON:1\n")
        time.sleep(0.5)
        self.app.processEvents()
        self.assertEqual(self.buttons.count(1), 1,
                         f"one physical press must produce one action: {self.buttons}")

        # a second, deliberate press later is a new action again
        time.sleep(0.3)
        os.write(self.master_fd, b"BUTTON:1\n")
        self.assertTrue(wait_for(lambda: self.buttons.count(1) == 2, 5.0))

    def test_validated_buttons_without_ready_are_still_handled_safely(self):
        """Device that never sends READY: first press is treated as startup
        noise, but the window then shortens so real presses keep working."""
        self.start_and_wait_open()
        os.write(self.master_fd, b"BUTTON:1\nBUTTON:2\n")
        self.assertTrue(wait_for(lambda: self.manager.state == STATE_CONNECTED, 5.0))
        deadline = time.monotonic() + STARTUP_IGNORE_GRACE + 0.5
        while time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.02)
        os.write(self.master_fd, b"BUTTON:3\n")
        self.assertTrue(wait_for(lambda: 3 in self.buttons, 5.0),
                        f"press after the shortened window must dispatch; "
                        f"buttons={self.buttons}")


@unittest.skipUnless(HAVE_QT, "PySide6 is required")
class WorkerResilienceTests(_PtyTestCase):
    """Bug 2: the reader must survive unexpected errors and keep working."""

    def test_unexpected_exception_does_not_kill_the_reader(self):
        """A one-off error in a dispatch path must not stop future presses."""
        original = self.manager.emit_button
        state = {"armed": True}

        def exploding(number: int) -> None:
            if state["armed"]:
                state["armed"] = False
                raise RuntimeError("simulated deleted Qt object")
            original(number)

        self.manager.emit_button = exploding  # type: ignore[method-assign]
        self.start_and_wait_open()
        os.write(self.master_fd, b"ABNODECK:READY\n")
        self.wait_until_operational()
        os.write(self.master_fd, b"BUTTON:1\n")  # triggers the injected error
        self.assertTrue(wait_for(lambda: not state["armed"], 5.0),
                        "injected error never fired")

        # the worker must close, release and reconnect (backoff <= 2 s)
        os.write(self.master_fd, b"BUTTON:3\n")
        self.assertTrue(
            wait_for(lambda: 3 in self.buttons, 15.0),
            "physical presses must keep working after an unexpected error "
            f"(buttons={self.buttons}, state={self.manager.state})",
        )
        self.assertEqual(self.manager.state, STATE_CONNECTED)

    def test_reconnect_to_a_new_device_node_keeps_dispatching(self):
        self.start_and_wait_open()
        os.write(self.master_fd, b"ABNODECK:READY\n")
        self.wait_until_operational()
        os.write(self.master_fd, b"BUTTON:1\n")
        self.assertTrue(wait_for(lambda: 1 in self.buttons, 5.0))

        # unplug -> the target vanishes (open fails with ENOENT)
        self.manager.configure(port="/dev/abno-deck-gone-port")
        self.assertTrue(wait_for(lambda: len(self.errors) >= 1, 8.0),
                        "a vanished port must be reported")

        # plug back in: fresh device node, fresh handshake
        self.master_fd, self.slave_fd = pty.openpty()
        self.port = os.ttyname(self.slave_fd)
        self.manager.configure(port=self.port)
        self.wait_until_port_open()
        os.write(self.master_fd, b"ABNODECK:READY\n")
        self.wait_until_operational()
        os.write(self.master_fd, b"BUTTON:2\n")
        self.assertTrue(wait_for(lambda: 2 in self.buttons, 8.0),
                        f"no dispatch after reconnect; buttons={self.buttons}")

    def test_stop_releases_the_claim_for_the_next_session(self):
        self.manager.start(self.port)
        self.assertTrue(wait_for(lambda: self.manager.is_running))
        self.manager.stop()
        self.assertNotIn(self.port, serial_io._OPEN_DEVICES)
        # a fresh manager must be able to open the same port again
        second = SerialManager(debounce_ms=250)
        received: list[int] = []
        second.buttonPressed.connect(received.append)
        self.manager = second  # tearDown stops it
        second.start(self.port)
        self.wait_until_port_open()
        os.write(self.master_fd, b"ABNODECK:READY\n")
        self.wait_until_operational()
        os.write(self.master_fd, b"BUTTON:1\n")
        self.assertTrue(wait_for(lambda: 1 in received, 5.0))


if __name__ == "__main__":
    unittest.main()
