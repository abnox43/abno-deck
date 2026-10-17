"""Strict parsing of the ESP32 serial protocol.

The firmware only ever sends three kinds of lines:

* ``ABNODECK:READY``        - handshake emitted after boot / reset
* ``BUTTON:1`` .. ``BUTTON:4`` - a physical button event
* anything else             - noise, malformed data or (potentially) garbage

This module is deliberately paranoid:

* Parsing is pure and side effect free, so it is trivially unit testable.
* Only the two whitelisted shapes are accepted; everything else is returned as
  ``UNKNOWN`` with a human readable reason and is **never** interpreted as a
  command.  The desktop application owns the action mapping, the microcontroller
  only owns button identifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .constants import BUTTON_PREFIX, MAX_BUTTON, MIN_BUTTON, READY_MARKER

# Full-line match: ``BUTTON:<digits>`` with nothing else around it.
_BUTTON_RE = re.compile(r"^BUTTON:(\d+)$")


class MessageKind(str, Enum):
    READY = "ready"
    BUTTON = "button"
    EMPTY = "empty"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ParsedMessage:
    """Result of parsing one raw serial line."""

    kind: MessageKind
    raw: str
    button: int | None = None
    reason: str = ""

    @property
    def is_ready(self) -> bool:
        return self.kind is MessageKind.READY

    @property
    def is_button(self) -> bool:
        return self.kind is MessageKind.BUTTON


def parse_line(line: str | bytes | None) -> ParsedMessage:
    """Parse one raw line coming from the ESP32.

    Accepts ``str`` or ``bytes`` (bytes are decoded as UTF-8 with ``replace``
    so a broken frame can never raise).  Returns a :class:`ParsedMessage`; the
    ``UNKNOWN`` kind carries a ``reason`` suitable for the event log.
    """
    if line is None:
        return ParsedMessage(MessageKind.EMPTY, "")

    if isinstance(line, (bytes, bytearray)):
        line = bytes(line).decode("utf-8", errors="replace")

    raw = line
    # Serial frames commonly end with CRLF; tolerate surrounding whitespace but
    # never strip characters in the middle of the message.
    text = line.strip()

    if not text:
        return ParsedMessage(MessageKind.EMPTY, raw)

    if text == READY_MARKER:
        return ParsedMessage(MessageKind.READY, raw)

    match = _BUTTON_RE.match(text)
    if match is None:
        if text.startswith(BUTTON_PREFIX):
            reason = "malformed button message (expected BUTTON:<1-4>)"
        else:
            reason = "unrecognised message (not part of the ABNO DECK protocol)"
        return ParsedMessage(MessageKind.UNKNOWN, raw, reason=reason)

    number = int(match.group(1), 10)
    if not (MIN_BUTTON <= number <= MAX_BUTTON):
        # e.g. BUTTON:0 / BUTTON:7 - valid syntax, invalid button.
        return ParsedMessage(
            MessageKind.UNKNOWN,
            raw,
            reason=f"button number {number} outside supported range "
            f"{MIN_BUTTON}-{MAX_BUTTON}",
        )

    return ParsedMessage(MessageKind.BUTTON, raw, button=number)


def is_protocol_line(line: str | bytes | None) -> bool:
    """Convenience helper: ``True`` only for known protocol messages."""
    return parse_line(line).kind in (MessageKind.READY, MessageKind.BUTTON)


__all__ = ["MessageKind", "ParsedMessage", "parse_line", "is_protocol_line",
           BUTTON_PREFIX, READY_MARKER]
