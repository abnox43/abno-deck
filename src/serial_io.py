"""Background serial communication with the ESP32.

Architecture:

* :class:`SerialManager` is a ``QObject`` living in the GUI thread.  It owns a
  single daemon worker thread (:meth:`SerialManager.start` / :meth:`stop`).
* The worker opens the port at 115200 baud, waits for ``ABNODECK:READY``,
  then streams lines.  Every line is parsed by the strict rules in
  :mod:`src.protocol`; only button identifiers 1-4 ever reach the GUI, and an
  action mapping is *never* read from the wire.
* All signals are emitted through Qt's queued connections, so slots always run
  in the GUI thread and the window never freezes.
* Reconnection is automatic with capped exponential backoff, and the port is
  opened with an exclusive lock plus an in-process registry so the same device
  can never be opened twice.
"""

from __future__ import annotations

import errno
import logging
import threading
import time

import serial
from serial import SerialException
from PySide6.QtCore import QObject, Signal

from .constants import (
    BAUD_RATE,
    CONNECT_RETRY_DELAY,
    DEFAULT_DEBOUNCE_MS,
    HANDSHAKE_TIMEOUT,
    READY_MARKER,
    RECONNECT_BACKOFF_MAX,
    RECONNECT_BACKOFF_START,
    SERIAL_READ_TIMEOUT,
    STARTUP_IGNORE_GRACE,
)
from .debounce import Debouncer
from .ports import detect_ports, find_port, suggest_port
from .protocol import MessageKind, parse_line

log = logging.getLogger(__name__)

STATE_DISCONNECTED = "disconnected"
STATE_CONNECTING = "connecting"
STATE_CONNECTED = "connected"

# In-process guard: never hold the same device open twice (e.g. two windows,
# or a stop/start race).  Module level on purpose.
_OPEN_LOCK = threading.Lock()
_OPEN_DEVICES: set[str] = set()


class SerialAccessError(RuntimeError):
    """Port could not be opened; ``hint`` carries user instructions."""

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.hint = hint


def permission_hint(device: str) -> str:
    return (
        f"No permission for {device}. Fix it without sudo-ing the app:\n"
        f"  ls -l {device}\n"
        f"  sudo usermod -aG dialout \"$USER\"   (log out and back in)\n"
        "or install the udev 'uaccess' rule from packaging/99-abno-deck.rules."
    )


class SerialWorker(threading.Thread):
    """Owns the serial port; runs until :meth:`request_stop` is honoured."""

    def __init__(self, manager: "SerialManager", target_port: str | None,
                 baud: int, debounce_ms: int, auto_reconnect: bool) -> None:
        super().__init__(name="abno-deck-serial", daemon=True)
        self._manager = manager
        self._target = target_port or ""
        self._baud = baud
        self._auto_reconnect = auto_reconnect
        self._stop_event = threading.Event()
        self._debouncer = Debouncer(debounce_ms)
        self._device: str | None = None
        # NOTE: never call this "_handle" - threading.Thread owns an attribute
        # of that name (the thread handle) and join() depends on it.
        self._serial_handle: serial.Serial | None = None

    # -- lifecycle ----------------------------------------------------------
    def request_stop(self) -> None:
        self._stop_event.set()

    def stop_now(self) -> None:
        """Force the current read to end (called from the manager)."""
        self._stop_event.set()
        handle = self._serial_handle
        if handle is not None:
            try:
                handle.cancel_read()
            except Exception:
                pass

    # -- port helpers -------------------------------------------------------
    def _claim(self, device: str) -> None:
        with _OPEN_LOCK:
            if device in _OPEN_DEVICES:
                raise SerialAccessError(f"{device} is already open by ABNO DECK")
            _OPEN_DEVICES.add(device)
        self._device = device

    def _release(self) -> None:
        device, self._device = self._device, None
        if device:
            with _OPEN_LOCK:
                _OPEN_DEVICES.discard(device)

    @staticmethod
    def _describe_open_error(device: str, exc: Exception) -> SerialAccessError:
        message = str(exc)
        lower = message.lower()
        if isinstance(exc, PermissionError) or "permission" in lower or "errno 13" in lower:
            return SerialAccessError(f"permission denied for {device}", permission_hint(device))
        if getattr(exc, "errno", None) == errno.EBUSY or "busy" in lower or "resource busy" in lower:
            return SerialAccessError(
                f"{device} is busy",
                "Another program is using the port (a serial monitor, another "
                "ABNO DECK instance?). Close it and try again.",
            )
        if "no such file" in lower or getattr(exc, "errno", None) == errno.ENOENT:
            return SerialAccessError(
                f"{device} disappeared",
                "The device was unplugged; ABNO DECK keeps retrying automatically.",
            )
        return SerialAccessError(f"cannot open {device}: {message}")

    # -- main loop ----------------------------------------------------------
    def run(self) -> None:
        """Own the port for the whole lifetime of the worker.

        Wrapped in try/except/finally on purpose: an unexpected exception must
        never kill the thread silently, and the device claim in the module
        level registry must be released on *every* path - a leaked claim would
        make every later reconnect fail with "already open by ABNO DECK"
        forever (buttons would be dead until the app is restarted).
        """
        try:
            self._run_loop()
        except Exception:
            log.exception("serial worker stopped unexpectedly")
            self._manager.emit_error(
                "serial worker stopped unexpectedly",
                "See the log file for the traceback - reconnecting.",
            )
        finally:
            self._close_handle(self._serial_handle)
            self._serial_handle = None
            self._release()
            self._manager.emit_state(STATE_DISCONNECTED)

    def _run_loop(self) -> None:
        backoff = RECONNECT_BACKOFF_START
        waiting_logged = False
        while not self._stop_event.is_set():
            device = self._target or suggest_port()
            if not device:
                if not waiting_logged:
                    # Log once per "no device" episode, not on every retry.
                    waiting_logged = True
                    self._manager.emit_state(STATE_CONNECTING)
                    self._manager.emit_log("info", "No serial device found - waiting for the ESP32")
                self._stop_event.wait(CONNECT_RETRY_DELAY)
                continue
            waiting_logged = False

            try:
                self._claim(device)
            except SerialAccessError as exc:
                self._manager.emit_error(str(exc), exc.hint)
                self._manager.emit_state(STATE_DISCONNECTED if not self._auto_reconnect
                                         else STATE_CONNECTING)
                if not self._auto_reconnect:
                    break
                self._stop_event.wait(CONNECT_RETRY_DELAY)
                continue

            self._manager.emit_state(STATE_CONNECTING)
            self._manager.emit_log("info", f"Opening {device} at {self._baud} baud")
            try:
                handle = serial.Serial(
                    port=device,
                    baudrate=self._baud,
                    timeout=SERIAL_READ_TIMEOUT,
                    write_timeout=SERIAL_READ_TIMEOUT,
                    exclusive=True,   # OS level guard against a second opener
                )
            except (SerialException, OSError) as exc:
                error = self._describe_open_error(device, exc)
                self._release()
                self._manager.emit_error(str(error), error.hint)
                if not self._auto_reconnect:
                    self._manager.emit_state(STATE_DISCONNECTED)
                    break
                self._manager.emit_state(STATE_CONNECTING)
                self._stop_event.wait(CONNECT_RETRY_DELAY)
                continue

            self._serial_handle = handle
            # Requirement: discard incomplete/stale buffered input, but keep
            # listening immediately - the handshake is processed normally.
            self._discard_stale_input(handle, device)
            try:
                ok = self._read_session(handle, device)
            except Exception:
                # Anything unexpected (closed file race, deleted Qt object, a
                # bug in a connected slot ...) must degrade to "connection
                # lost" and reconnect - never to a dead reader thread.
                log.exception("unexpected error while reading from %s", device)
                self._manager.emit_error(
                    f"unexpected error while reading from {device}",
                    "See the log file for the traceback - reconnecting.",
                )
                ok = False
            finally:
                self._close_handle(handle)
                self._serial_handle = None
                self._release()

            if self._stop_event.is_set():
                break
            if not ok and not self._auto_reconnect:
                break

            self._manager.emit_state(STATE_CONNECTING)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)
            self._manager.emit_log(
                "warning",
                f"Connection to {device} lost - retrying in {backoff:.0f}s",
            )
            self._stop_event.wait(backoff)
            backoff = max(backoff, RECONNECT_BACKOFF_START)

    def _discard_stale_input(self, handle: serial.Serial, device: str) -> None:
        """Drop everything that was buffered in the kernel before we opened.

        The tty buffer (and the USB-UART bridge's own FIFO) can hold button
        presses made while ABNO DECK was not listening.  Dispatching them on
        connect would replay old presses as new ones, which is how all four
        keys could fire at startup.  Only *pre-existing* bytes are read here;
        live data arriving afterwards - including the READY handshake - is
        preserved and processed normally.
        """
        discarded = 0
        try:
            pending = handle.in_waiting or 0
            stale = handle.read(pending) if pending else b""
            discarded += len(stale or b"")
            # If the stale chunk ends mid-line, drop the rest of that line too,
            # otherwise it would be glued to the first live line after opening
            # (a stale "BUTTON:" plus a live "1\\n" would fake a press).  Only
            # done when stale data existed, and bounded by the read timeout.
            if stale and not stale.endswith(b"\n"):
                tail = handle.readline()
                discarded += len(tail or b"")
        except (SerialException, OSError, ValueError) as exc:
            self._manager.emit_log("warning", f"Could not flush stale input on {device}: {exc}")
        if discarded:
            self._manager.emit_log(
                "info",
                f"Discarded {discarded} byte(s) of stale buffered input on {device}",
            )

    def _close_startup_window(self, ignored: int) -> None:
        if ignored:
            self._manager.emit_log(
                "info",
                f"Startup window closed - ignored {ignored} startup button "
                "event(s); real presses are dispatched from now on",
            )

    def _read_session(self, handle: serial.Serial, device: str) -> bool:
        """Read until error/disconnect. Returns True for a clean handshake.

        Startup safety: opening the port toggles DTR/RTS, which resets the
        ESP32.  Everything that arrives in the wake of that reset (replayed or
        kernel-buffered presses, boot pin glitches that pass a naive firmware
        debounce) is *validated and logged but not dispatched* until the
        startup window closes - either READY_MARKER + STARTUP_IGNORE_GRACE, or
        (if the device never sends READY) a short window after the port opened.
        After that window every validated press is dispatched exactly once.
        """
        now = time.monotonic()
        deadline = now + HANDSHAKE_TIMEOUT
        # Outer bound of the startup window when no READY ever arrives.
        startup_until = deadline + STARTUP_IGNORE_GRACE
        ready_seen = False      # READY handshake or first valid line seen
        ready_ever = False      # the READY marker specifically was received
        ignored_startup = 0
        self._manager.emit_state(STATE_CONNECTING)

        while not self._stop_event.is_set():
            try:
                raw = handle.readline()
            except (SerialException, OSError, ValueError) as exc:
                # ValueError: "operation on closed file" after a close race -
                # treat it like a disconnect instead of killing the thread.
                self._manager.emit_error(f"read error on {device}: {exc}",
                                         "The device was disconnected or the port vanished.")
                self._close_startup_window(ignored_startup)
                return False

            if raw:
                try:
                    message = parse_line(raw)
                    # Requirement: log every incoming line (bounded, escaped).
                    self._manager.emit_log(
                        "debug",
                        "recv " + repr(message.raw).strip("'")[:120],
                    )

                    if message.kind is MessageKind.EMPTY:
                        continue

                    if message.kind is MessageKind.UNKNOWN:
                        # Bootloader text, garbage, out-of-range numbers ...
                        self._manager.emit_malformed(message.raw, message.reason)
                        continue

                    if message.kind is MessageKind.READY:
                        # Requirement: READY only updates the connection status.
                        ready_seen = True
                        ready_ever = True
                        startup_until = min(
                            startup_until, time.monotonic() + STARTUP_IGNORE_GRACE
                        )
                        self._manager.emit_state(STATE_CONNECTED)
                        self._manager.emit_ready()
                        self._manager.emit_log("info", f"Handshake received ({READY_MARKER})")
                        self._close_startup_window(ignored_startup)
                        ignored_startup = 0
                        continue

                    # MessageKind.BUTTON - a validated BUTTON:1..4 line.
                    button = message.button
                    if not ready_seen:
                        # Device was booted before we attached: still connected.
                        ready_seen = True
                        self._manager.emit_state(STATE_CONNECTED)
                        self._manager.emit_log(
                            "info",
                            "Port is open but no READY was received yet "
                            "(the ESP32 may have been started earlier)",
                        )

                    if time.monotonic() < startup_until:
                        # Startup/reset burst: validated and logged, never
                        # dispatched - opening the app must never execute
                        # button actions.  Without a READY handshake the first
                        # discarded event shortens the window so genuine
                        # presses are not blocked for long.
                        ignored_startup += 1
                        if not ready_ever:
                            startup_until = min(
                                startup_until, time.monotonic() + STARTUP_IGNORE_GRACE
                            )
                        self._manager.emit_log(
                            "info",
                            f"Ignored BUTTON:{button} received during the "
                            "startup window (reset/buffered input, not a "
                            "user press)",
                        )
                        continue

                    if self._debouncer.allow(button):
                        self._manager.emit_button(button)
                    else:
                        self._manager.emit_log(
                            "debug",
                            f"Debounced duplicate BUTTON:{button}",
                        )
                    continue
                except Exception:
                    # One bad line (or a bug in a dispatch slot) must never
                    # stop the reader.
                    log.exception("failed to process a serial line on %s", device)
                    continue

            # timeout with an empty line
            if not ready_seen and time.monotonic() >= deadline:
                # The port is open and readable - report it as connected, but
                # do not pretend a handshake happened.
                ready_seen = True
                self._manager.emit_state(STATE_CONNECTED)
                self._manager.emit_log(
                    "warning",
                    f"{device} is open but {READY_MARKER} was not received. "
                    "Press the ESP32 reset button if the device seems dead.",
                )
        self._close_startup_window(ignored_startup)
        return True

    @staticmethod
    def _close_handle(handle: serial.Serial | None) -> None:
        if handle is None:
            return
        try:
            handle.close()
        except Exception:
            pass


class SerialManager(QObject):
    """GUI-facing facade around :class:`SerialWorker`."""

    stateChanged = Signal(str)          # disconnected | connecting | connected
    readyReceived = Signal()            # ABNODECK:READY handshake
    buttonPressed = Signal(int)         # 1..4, already debounced
    malformedReceived = Signal(str, str)  # raw line, reason
    errorOccurred = Signal(str, str)      # message, hint
    logged = Signal(str, str)             # level, message

    def __init__(self, debounce_ms: int = DEFAULT_DEBOUNCE_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: SerialWorker | None = None
        self._state = STATE_DISCONNECTED
        self._target_port = ""
        self._baud = BAUD_RATE
        self._debounce_ms = debounce_ms
        self._auto_reconnect = True
        self._last_error = ""

    # -- properties ---------------------------------------------------------
    @property
    def state(self) -> str:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    @property
    def target_port(self) -> str:
        return self._target_port

    @property
    def baud_rate(self) -> int:
        return self._baud

    @property
    def debounce_ms(self) -> int:
        return self._debounce_ms

    # -- public API ---------------------------------------------------------
    def configure(self, *, port: str | None = None, baud: int | None = None,
                  debounce_ms: int | None = None, auto_reconnect: bool | None = None) -> None:
        """Update options; a running connection is only restarted on port/baud change."""
        restart = False
        if port is not None and port != self._target_port:
            self._target_port = port.strip()
            restart = True
        if baud is not None and baud != self._baud:
            self._baud = baud
            restart = True
        if debounce_ms is not None:
            self._debounce_ms = debounce_ms
        if auto_reconnect is not None:
            self._auto_reconnect = bool(auto_reconnect)
        if restart and self.is_running:
            self.stop()
            self.start()

    def start(self, port: str | None = None) -> None:
        """Start (or restart) the connection worker."""
        if port is not None:
            self._target_port = port.strip()
        if self.is_running:
            self.stop()
        self._worker = SerialWorker(
            self,
            target_port=self._target_port,
            baud=self._baud,
            debounce_ms=self._debounce_ms,
            auto_reconnect=self._auto_reconnect,
        )
        self.emit_state(STATE_CONNECTING)
        self.emit_log("info", "Serial connection starting")
        self._worker.start()

    def stop(self) -> None:
        """Stop the worker and release the port. Safe to call repeatedly."""
        worker, self._worker = self._worker, None
        if worker is None:
            return
        worker.request_stop()
        worker.stop_now()
        worker.join(timeout=3.0)
        if worker.is_alive():
            log.warning("serial worker did not stop within 3s")
        self.emit_state(STATE_DISCONNECTED)

    # -- helpers used by the worker (thread safe via queued signals) --------
    @staticmethod
    def _safe_emit(signal, *args) -> bool:
        """Emit without letting a deleted Qt object kill the worker thread."""
        try:
            signal.emit(*args)
            return True
        except RuntimeError:
            log.debug("dropped signal emission: Qt object already deleted")
            return False

    def emit_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            if state == STATE_CONNECTED:
                self._last_error = ""  # a fresh connection resets error de-duplication
            self._safe_emit(self.stateChanged, state)

    def emit_ready(self) -> None:
        self._safe_emit(self.readyReceived)

    def emit_button(self, number: int) -> None:
        self._safe_emit(self.buttonPressed, int(number))

    def emit_malformed(self, raw: str, reason: str) -> None:
        text = (raw or "").strip()
        if len(text) > 60:
            text = text[:57] + "..."
        self._safe_emit(self.malformedReceived, text, reason)
        # Protocol-shaped garbage is worth a warning; ordinary bootloader text
        # is normal traffic and only logged at debug level.
        level = "warning" if "button" in (reason or "").lower() else "debug"
        self.emit_log(level, f"Ignored serial input: {text!r} ({reason})")

    def emit_error(self, message: str, hint: str = "") -> None:
        if message == self._last_error:
            # Reconnect loops can hit the same problem every few seconds; the
            # GUI already shows it once, keep the log readable.
            log.debug("serial error (repeat): %s", message)
            return
        self._last_error = message
        log.error("%s", message)
        self._safe_emit(self.errorOccurred, message, hint)

    def emit_log(self, level: str, message: str) -> None:
        log.log(getattr(logging, level.upper(), logging.INFO), "%s", message)
        self._safe_emit(self.logged, level, message)


def list_ports_for_ui() -> list[tuple[str, str]]:
    """``[(device, label), ...]`` including a synthetic auto-detect entry."""
    entries: list[tuple[str, str]] = [("", "Auto-detect (recommended)")]
    for info in detect_ports():
        entries.append((info.device, info.label()))
    return entries


def port_exists(device: str) -> bool:
    return find_port(device) is not None


__all__ = [
    "STATE_CONNECTED",
    "STATE_CONNECTING",
    "STATE_DISCONNECTED",
    "SerialAccessError",
    "SerialManager",
    "list_ports_for_ui",
    "permission_hint",
    "port_exists",
]
