"""Detection of the external tools ABNO DECK can use on Linux.

Everything here is *detection only*: no action is ever executed from this
module.  The GUI uses it to explain missing dependencies instead of failing
silently, and the action runners use it to pick a backend or to return an
honest error message.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class DepStatus:
    key: str
    label: str
    found: bool
    path: str
    purpose: str
    hint: str  # install / fix instructions shown when missing

    def describe(self) -> str:
        state = self.path if self.found else "not found"
        return f"{self.label}: {state} — {self.purpose}"


def which(command: str) -> str:
    return shutil.which(command) or ""


def session_type() -> str:
    """Return ``x11``, ``wayland`` or ``unknown`` for the current session."""
    explicit = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if explicit in ("x11", "wayland"):
        return explicit
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def is_wayland() -> bool:
    return session_type() == "wayland"


@lru_cache(maxsize=1)
def shortcut_backend() -> DepStatus | None:
    """Best available tool for synthesising key presses.

    Order matters: on Wayland only wtype/ydotool can inject keys, on X11
    xdotool is the most reliable option.
    """
    candidates = (
        ("xdotool", "xdotool", "X11 key injection", "sudo apt install xdotool"),
        ("wtype", "wtype", "Wayland (wlroots) key injection", "sudo apt install wtype"),
        ("ydotool", "ydotool", "Wayland/uinput key injection (needs ydotoold)",
         "sudo apt install ydotool && sudo systemctl enable --now ydotoold"),
    )
    order = ("wtype", "ydotool", "xdotool") if is_wayland() else ("xdotool", "wtype", "ydotool")
    statuses = {
        key: DepStatus(key, key, bool(path), path, purpose, hint)
        for key, label, purpose, hint in candidates
        for path in (which(key),)
    }
    for key in order:
        status = statuses[key]
        if status.found:
            return status
    return None


@lru_cache(maxsize=1)
def media_backend() -> DepStatus | None:
    """Best available tool for MPRIS media control."""
    playerctl = which("playerctl")
    if playerctl:
        return DepStatus("playerctl", "playerctl", True, playerctl,
                         "MPRIS media control", "sudo apt install playerctl")
    dbus_send = which("dbus-send")
    if dbus_send:
        return DepStatus("dbus-send", "dbus-send", True, dbus_send,
                         "MPRIS media control via D-Bus", "sudo apt install dbus-bin")
    return None


@lru_cache(maxsize=1)
def uri_backend() -> DepStatus | None:
    """Best available tool for opening a URL in the default browser."""
    for key, hint in (("gio", "sudo apt install libglib2.0-bin"),
                      ("xdg-open", "sudo apt install xdg-utils")):
        path = which(key)
        if path:
            return DepStatus(key, key, True, path, "open URLs in the default handler", hint)
    return None


def all_dependencies() -> list[DepStatus]:
    """Status list shown on the settings screen."""
    status: list[DepStatus] = []
    for key, purpose, hint in (
        ("gio", "open URLs in the default handler", "sudo apt install libglib2.0-bin"),
        ("xdg-open", "open URLs (fallback)", "sudo apt install xdg-utils"),
        ("xdotool", "X11 keyboard shortcuts", "sudo apt install xdotool"),
        ("wtype", "Wayland keyboard shortcuts", "sudo apt install wtype"),
        ("ydotool", "Wayland keyboard shortcuts (uinput)", "sudo apt install ydotool"),
        ("playerctl", "media playback control", "sudo apt install playerctl"),
        ("dbus-send", "MPRIS fallback (no playerctl)", "sudo apt install dbus-bin"),
    ):
        path = which(key)
        status.append(DepStatus(key, key, bool(path), path, purpose, hint))
    status.append(DepStatus("session", "session type", True, session_type(),
                            "graphical session in use", ""))
    return status


def missing_dependency_report() -> list[str]:
    """Warnings for features that cannot work in this session."""
    warnings: list[str] = []
    if shortcut_backend() is None:
        warnings.append(
            "No keyboard shortcut backend found. Install one with: "
            "sudo apt install xdotool (X11) or sudo apt install wtype (Wayland)"
        )
    if media_backend() is None:
        warnings.append("No media backend found. Install with: sudo apt install playerctl")
    if uri_backend() is None:
        warnings.append("No URL handler found. Install with: sudo apt install xdg-utils")
    if is_wayland():
        warnings.append(
            "Wayland session detected: keyboard shortcuts need wtype or ydotool; "
            "xdotool cannot inject keys here"
        )
    return warnings


def reset_cache() -> None:
    """Testing helper: forget cached detection results."""
    shortcut_backend.cache_clear()
    media_backend.cache_clear()
    uri_backend.cache_clear()


__all__ = [
    "DepStatus",
    "all_dependencies",
    "is_wayland",
    "media_backend",
    "missing_dependency_report",
    "reset_cache",
    "session_type",
    "shortcut_backend",
    "uri_backend",
    "which",
]
