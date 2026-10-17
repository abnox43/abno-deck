"""Data model for ABNO DECK profiles and buttons (Qt free).

A *profile* is a JSON document describing four buttons::

    {
      "schema": 1,
      "id": "default",
      "name": "Default",
      "buttons": [
        {"slot": 1, "name": "Terminal", "icon": "🖥️",
         "action": {"type": "launch_app", "executable": "x-terminal-emulator",
                     "arguments": ""}}
      ]
    }

Sanitisers accept arbitrary (possibly corrupt) input and return a valid
document; validators return a list of human readable problems without touching
the filesystem, so both are easy to unit test.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

from .constants import (
    ACTION_TYPES,
    ALLOWED_URL_SCHEMES,
    MEDIA_COMMANDS,
    MEDIA_LABELS,
    MIN_BUTTON,
    NUM_BUTTONS,
    PROFILE_SCHEMA_VERSION,
)

SlugError = ValueError

_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")
_SHORTCUT_TOKEN_RE = re.compile(r"^[A-Za-z0-9_+]+$")
_URL_RE = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<rest>\S.*)$")

SHORTCUT_MODIFIERS = ("ctrl", "alt", "shift", "super", "meta", "mod4", "mod5")

DEFAULT_ICON = "⬜"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def slugify(text: str, fallback: str = "profile") -> str:
    """Build a filesystem-safe identifier from a profile name."""
    normalised = unicodedata.normalize("NFKD", str(text or ""))
    slug = _NON_SLUG_RE.sub("-", normalised.lower()).strip("-")
    slug = slug[:48].strip("-")
    if not slug or slug in (".", ".."):
        return fallback
    return slug


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _clean_lines(value: Any) -> str:
    """Collapse a possible list-of-lines into a single trimmed string."""
    if isinstance(value, (list, tuple)):
        return " ".join(_as_str(item).strip() for item in value).strip()
    return _as_str(value).strip()


# --------------------------------------------------------------------------
# actions
# --------------------------------------------------------------------------
def default_action() -> dict:
    return {"type": "none"}


def sanitize_action(raw: Any) -> dict:
    """Return a *valid* action dict derived from arbitrary input."""
    if not isinstance(raw, dict):
        return default_action()

    action_type = _as_str(raw.get("type")).strip().lower()
    if action_type not in ACTION_TYPES:
        return default_action()

    action: dict = {"type": action_type}

    if action_type == "launch_app":
        action["executable"] = _as_str(raw.get("executable")).strip()
        action["arguments"] = _clean_lines(raw.get("arguments"))
    elif action_type == "open_url":
        action["url"] = _as_str(raw.get("url")).strip()
    elif action_type == "shortcut":
        action["keys"] = _as_str(raw.get("keys")).strip()
    elif action_type == "media":
        media = _as_str(raw.get("command")).strip().lower()
        action["command"] = media if media in MEDIA_COMMANDS else "play_pause"
    elif action_type == "command":
        action["command"] = _as_str(raw.get("command")).strip()
        action["use_shell"] = bool(raw.get("use_shell", False))
        action["confirm"] = bool(raw.get("confirm", True))
    return action


def parse_url(url: str) -> tuple[str, str] | None:
    """Return ``(scheme, rest)`` for an acceptable absolute URL."""
    match = _URL_RE.match((url or "").strip())
    if not match:
        return None
    return match.group("scheme").lower(), match.group("rest")


def contains_shell_metacharacters(command: str) -> bool:
    return any(char in (command or "") for char in ("|", "&", ";", "<", ">", "$(", "`"))


def parse_shortcut(keys: str) -> tuple[list[str], str] | None:
    """Split ``Ctrl+Alt+T`` into ``(["ctrl", "alt"], "t")``.

    Returns ``None`` when the string cannot be a valid shortcut.  Only a very
    conservative syntax is accepted here; the actual key name is checked
    against the session backend when the shortcut runs.
    """
    text = _as_str(keys).strip()
    if not text or len(text) > 64:
        return None
    if not _SHORTCUT_TOKEN_RE.match(text):
        return None

    parts = [part.strip().lower() for part in text.split("+")]
    if any(not part for part in parts):
        return None
    if len(parts) > 4:
        return None

    *modifier_tokens, key = parts
    modifiers: list[str] = []
    for token in modifier_tokens:
        normalised = "ctrl" if token in ("control", "ctrl") else token
        normalised = "super" if normalised == "meta" else normalised
        if normalised not in SHORTCUT_MODIFIERS:
            return None
        if normalised in modifiers:
            return None
        modifiers.append(normalised)
    # A shortcut without a modifier is allowed (e.g. F13 media keys).
    return modifiers, key


def validate_action(action: dict) -> list[str]:
    """Static validation of an action; no subprocess, no side effects."""
    if not isinstance(action, dict):
        return ["action must be an object"]
    action_type = _as_str(action.get("type")).strip()
    if action_type not in ACTION_TYPES:
        return [f"unknown action type {action_type!r} "
                f"(expected one of: {', '.join(ACTION_TYPES)})"]

    errors: list[str] = []
    if action_type == "launch_app":
        executable = _as_str(action.get("executable")).strip()
        if not executable:
            errors.append("launch_app requires an executable")
        elif any(char in executable for char in " \t\n"):
            errors.append(
                "executable must be a single program name or path "
                "(put extra parameters into the arguments field)"
            )
        if "\n" in _as_str(action.get("arguments")):
            errors.append("arguments must stay on a single line")
    elif action_type == "open_url":
        url = _as_str(action.get("url")).strip()
        parsed = parse_url(url)
        if parsed is None:
            errors.append("open_url requires an absolute URL like https://example.org")
        elif parsed[0] not in ALLOWED_URL_SCHEMES:
            errors.append(
                f"URL scheme {parsed[0]!r} is not allowed "
                f"(use: {', '.join(ALLOWED_URL_SCHEMES)})"
            )
    elif action_type == "shortcut":
        if parse_shortcut(_as_str(action.get("keys"))) is None:
            errors.append("shortcut requires a combination such as Ctrl+Alt+T")
    elif action_type == "media":
        if _as_str(action.get("command")).strip().lower() not in MEDIA_COMMANDS:
            errors.append(
                "media action requires one of: "
                + ", ".join(MEDIA_COMMANDS)
            )
    elif action_type == "command":
        command = _as_str(action.get("command")).strip()
        if not command:
            errors.append("command action requires a command line")
        elif contains_shell_metacharacters(command) and not action.get("use_shell"):
            errors.append(
                "this command contains shell operators (| & ; > < $ `); "
                "enable 'allow shell interpretation' explicitly or remove them"
            )
        if len(command) > 2000:
            errors.append("command line is too long (max 2000 characters)")
    return errors


def describe_action(action: dict) -> str:
    """One-line description shown on the deck buttons and in the log."""
    safe = sanitize_action(action)
    kind = safe["type"]
    if kind == "launch_app":
        exe = safe["executable"] or "?"
        return f"Launch {exe}"
    if kind == "open_url":
        return f"Open {safe['url'] or '?'}"
    if kind == "shortcut":
        return f"Shortcut {safe['keys'] or '?'}"
    if kind == "media":
        return f"Media: {MEDIA_LABELS.get(safe['command'], safe['command'])}"
    if kind == "command":
        prefix = "Shell: " if safe.get("use_shell") else "Command: "
        command = safe["command"]
        if len(command) > 32:
            command = command[:29] + "..."
        return prefix + (command or "?")
    return "No action"


# --------------------------------------------------------------------------
# buttons
# --------------------------------------------------------------------------
def new_button(slot: int, name: str = "", icon: str = "", action: dict | None = None) -> dict:
    return sanitize_button(
        {
            "slot": slot,
            "name": name or f"Button {slot}",
            "icon": icon or DEFAULT_ICON,
            "action": action or default_action(),
        },
        slot=slot,
    )


def sanitize_button(raw: Any, slot: int | None = None) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    target_slot = slot if slot is not None else _coerce_slot(raw.get("slot"))
    name = _as_str(raw.get("name")).strip() or f"Button {target_slot}"
    icon = _as_str(raw.get("icon")).strip() or DEFAULT_ICON
    if len(name) > 60:
        name = name[:60]
    if len(icon) > 8:
        icon = icon[:8]
    return {
        "slot": target_slot,
        "name": name,
        "icon": icon,
        "action": sanitize_action(raw.get("action")),
    }


def _coerce_slot(value: Any) -> int:
    try:
        slot = int(value)
    except (TypeError, ValueError):
        slot = MIN_BUTTON
    return min(max(slot, MIN_BUTTON), NUM_BUTTONS)


def validate_button(button: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(button, dict):
        return ["button must be an object"]
    slot = button.get("slot")
    if not isinstance(slot, int) or not (MIN_BUTTON <= slot <= NUM_BUTTONS):
        errors.append(f"invalid slot {slot!r} (expected {MIN_BUTTON}-{NUM_BUTTONS})")
    name = button.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("button name must not be empty")
    icon = button.get("icon")
    if not isinstance(icon, str) or not icon.strip():
        errors.append("button icon must not be empty")
    errors.extend(validate_action(button.get("action")))
    return errors


# --------------------------------------------------------------------------
# profiles
# --------------------------------------------------------------------------
def default_buttons() -> list[dict]:
    """Four starter buttons used by the built-in default profile."""
    return [
        new_button(1, "Terminal", "🖥️",
                   {"type": "launch_app", "executable": "x-terminal-emulator",
                    "arguments": ""}),
        new_button(2, "Web", "🌐",
                   {"type": "open_url", "url": "https://duckduckgo.com"}),
        new_button(3, "Play/Pause", "⏯️",
                   {"type": "media", "command": "play_pause"}),
        new_button(4, "Lock", "🔒",
                   {"type": "shortcut", "keys": "Ctrl+Alt+L"}),
    ]


def new_profile(name: str, profile_id: str | None = None) -> dict:
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    identifier = slugify(profile_id or name)
    return {
        "schema": PROFILE_SCHEMA_VERSION,
        "id": identifier,
        "name": (str(name).strip() or "Profile")[:60],
        "created": now,
        "buttons": default_buttons(),
    }


def sanitize_profile(raw: Any, profile_id: str | None = None) -> dict:
    """Coerce arbitrary input into a fully valid profile document."""
    if not isinstance(raw, dict):
        return new_profile("Profile", profile_id)

    identifier = slugify(_as_str(raw.get("id")) or _as_str(profile_id) or "profile")
    name = _as_str(raw.get("name")).strip() or "Profile"
    profile = {
        "schema": PROFILE_SCHEMA_VERSION,
        "id": identifier,
        "name": name[:60],
        "created": _as_str(raw.get("created")) or time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "buttons": [],
    }

    raw_buttons = raw.get("buttons")
    by_slot: dict[int, dict] = {}
    if isinstance(raw_buttons, (list, tuple)):
        for index, entry in enumerate(raw_buttons):
            slot = index + 1
            if isinstance(entry, dict) and isinstance(entry.get("slot"), int):
                slot = _coerce_slot(entry["slot"])
            if slot in by_slot:          # duplicate slot -> fall back to position
                slot = index + 1 if index + 1 not in by_slot else None
            if slot is None:
                continue
            by_slot[slot] = sanitize_button(entry, slot=slot)

    for slot in range(1, NUM_BUTTONS + 1):
        profile["buttons"].append(by_slot.get(slot) or new_button(slot))
    return profile


def validate_profile(profile: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(profile, dict):
        return ["profile must be an object"]
    if not _as_str(profile.get("name")).strip():
        errors.append("profile name must not be empty")
    if not _as_str(profile.get("id")).strip():
        errors.append("profile id must not be empty")
    buttons = profile.get("buttons")
    if not isinstance(buttons, (list, tuple)):
        errors.append("profile must contain a list of buttons")
        return errors
    if len(buttons) != NUM_BUTTONS:
        errors.append(f"profile must contain exactly {NUM_BUTTONS} buttons")
    seen_slots: set[int] = set()
    for index, button in enumerate(buttons):
        if not isinstance(button, dict):
            errors.append(f"button #{index + 1} is not an object")
            continue
        slot = button.get("slot")
        if isinstance(slot, int) and slot in seen_slots:
            errors.append(f"duplicate button slot {slot}")
        elif isinstance(slot, int):
            seen_slots.add(slot)
        errors.extend(f"button #{index + 1}: {problem}"
                      for problem in validate_button(button))
    return errors


__all__ = [
    "ACTION_TYPES",
    "MEDIA_COMMANDS",
    "SHORTCUT_MODIFIERS",
    "SlugError",
    "contains_shell_metacharacters",
    "default_action",
    "default_buttons",
    "describe_action",
    "new_button",
    "new_profile",
    "parse_shortcut",
    "parse_url",
    "sanitize_action",
    "sanitize_button",
    "sanitize_profile",
    "slugify",
    "validate_action",
    "validate_button",
    "validate_profile",
]
