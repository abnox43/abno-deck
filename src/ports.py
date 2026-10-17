"""Serial port discovery for ABNO DECK (Qt free, safe to test headless)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .constants import KNOWN_USB_IDS

try:  # pyserial is a hard requirement of the app but keep import errors explicit
    from serial.tools import list_ports
except Exception:  # pragma: no cover - environment without pyserial
    list_ports = None  # type: ignore[assignment]

_TTY_RE = re.compile(r"^/dev/tty(USB|ACM|AP)\d+$")
_HINT_RE = re.compile(
    r"esp32|esp8266|esp-idf|cp210|ch340|ch341|ch910|slab|usb.?serial|uart",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PortInfo:
    """One detected serial device."""

    device: str
    description: str = ""
    manufacturer: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str = ""
    candidate: bool = False

    @property
    def usb_id(self) -> str:
        if self.vid is None:
            return ""
        pid = self.pid or 0
        return f"{self.vid:04X}:{pid:04X}"

    @property
    def chip_hint(self) -> str:
        if self.vid in KNOWN_USB_IDS:
            return KNOWN_USB_IDS[self.vid]
        return ""

    def label(self) -> str:
        """Human readable label used by the port drop-down."""
        bits = [self.device]
        detail = self.description.strip() or self.manufacturer.strip()
        if detail and detail != self.device:
            bits.append(detail)
        if self.usb_id:
            bits.append(self.usb_id)
        if self.chip_hint:
            bits.append(self.chip_hint)
        # de-duplicate while preserving order
        seen: set[str] = set()
        unique = []
        for bit in bits:
            if bit and bit not in seen:
                seen.add(bit)
                unique.append(bit)
        return " — ".join(unique)


def _is_candidate(device: str, description: str, vid: int | None) -> bool:
    if vid is not None and vid in KNOWN_USB_IDS:
        return True
    if _TTY_RE.match(device or ""):
        return True
    if _HINT_RE.search(description or ""):
        return True
    return False


def detect_ports() -> list[PortInfo]:
    """Return every serial device currently visible to the system.

    Never raises: an environment without pyserial (or with a broken udev cache)
    simply yields an empty list, which the UI reports as "no ports found".
    """
    if list_ports is None:
        return []

    results: list[PortInfo] = []
    try:
        ports: Iterable = list(list_ports.comports())
    except Exception:
        return []

    for port in ports:
        device = getattr(port, "device", "") or ""
        if not device:
            continue
        vid = getattr(port, "vid", None)
        description = getattr(port, "description", "") or ""
        results.append(
            PortInfo(
                device=device,
                description=description,
                manufacturer=getattr(port, "manufacturer", "") or "",
                vid=vid,
                pid=getattr(port, "pid", None),
                serial_number=getattr(port, "serial_number", "") or "",
                candidate=_is_candidate(device, description, vid),
            )
        )

    # ESP32-looking devices first, then stable alphabetical order.
    results.sort(key=lambda info: (not info.candidate, info.device))
    return results


def suggest_port() -> str | None:
    """Best automatic guess: the first ESP32-like USB serial port.

    Only candidate devices (known USB bridge IDs, ttyUSB/ttyACM/USB serial
    descriptions) are chosen automatically. Hardware UARTs such as /dev/ttyS0
    are ignored - they belong to other equipment and usually lack permissions.
    Use manual port selection in the settings if you really need one.
    """
    ports = detect_ports()
    for port in ports:
        if port.candidate:
            return port.device
    return None


def find_port(device: str) -> PortInfo | None:
    for port in detect_ports():
        if port.device == device:
            return port
    return None


__all__ = ["PortInfo", "detect_ports", "suggest_port", "find_port"]
