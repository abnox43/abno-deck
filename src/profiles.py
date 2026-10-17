"""Profile and settings persistence for ABNO DECK.

Layout of ``~/.config/abno-deck``::

    settings.json          application settings (active profile, serial, ...)
    profiles/<id>.json     one file per profile (create/rename = file ops)
    backups/               rotation-safe copies made before every save wave
    abno-deck.log          application log (see src.logsetup)

Every mutation is written to disk immediately ("save as you go"), so closing
the app (or crashing it) never loses a button configuration.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Iterator

from .constants import (
    BACKUPS_DIR_NAME,
    CONFIG_DIR_NAME,
    CONFIG_ENV_VAR,
    CONFIG_SCHEMA_VERSION,
    DEFAULT_DEBOUNCE_MS,
    NUM_BUTTONS,
    PROFILES_DIR_NAME,
    SETTINGS_FILE_NAME,
)
from .models import new_profile, sanitize_profile, slugify, validate_profile
from .storage import ensure_dir, load_json_or_quarantine, read_json, write_json

log = logging.getLogger(__name__)

DEFAULT_PROFILE_NAME = "Default"
_ID_SANITIZE_RE = re.compile(r"[^a-z0-9-]+")


class ProfileError(RuntimeError):
    """Raised for user level profile problems (last profile, bad names...)."""


def default_config_dir() -> Path:
    """``~/.config/abno-deck`` unless overridden by env var / CLI."""
    override = os.environ.get(CONFIG_ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / CONFIG_DIR_NAME


def default_settings() -> dict:
    return {
        "schema": CONFIG_SCHEMA_VERSION,
        "active_profile": "",
        "serial": {
            "port": "",              # empty string = auto detect
            "auto_connect": True,
            "auto_reconnect": True,
            "baud_rate": 115200,
            "debounce_ms": DEFAULT_DEBOUNCE_MS,
        },
        "log_level": "INFO",
        "window": {"width": 1080, "height": 720},
    }


def sanitize_settings(raw: Any) -> dict:
    settings = default_settings()
    if not isinstance(raw, dict):
        return settings

    active = raw.get("active_profile")
    if isinstance(active, str):
        settings["active_profile"] = slugify(active, fallback="")

    serial = raw.get("serial")
    if isinstance(serial, dict):
        port = serial.get("port")
        if isinstance(port, str):
            settings["serial"]["port"] = port.strip()[:120]
        for flag in ("auto_connect", "auto_reconnect"):
            value = serial.get(flag)
            if isinstance(value, bool):
                settings["serial"][flag] = value
        baud = serial.get("baud_rate")
        if isinstance(baud, int) and 1200 <= baud <= 4_000_000:
            settings["serial"]["baud_rate"] = baud
        debounce = serial.get("debounce_ms")
        if isinstance(debounce, int) and 0 <= debounce <= 5000:
            settings["serial"]["debounce_ms"] = debounce

    level = raw.get("log_level")
    if isinstance(level, str) and level.upper() in ("DEBUG", "INFO", "WARNING", "ERROR"):
        settings["log_level"] = level.upper()

    window = raw.get("window")
    if isinstance(window, dict):
        for key in ("width", "height"):
            value = window.get(key)
            if isinstance(value, int) and 200 <= value <= 10000:
                settings["window"][key] = value

    return settings


class ProfileStore:
    """Owns every profile file plus ``settings.json``."""

    def __init__(self, config_dir: Path | str | None = None) -> None:
        self.config_dir = Path(config_dir).expanduser() if config_dir else default_config_dir()
        self.profiles_dir = self.config_dir / PROFILES_DIR_NAME
        self.settings_path = self.config_dir / SETTINGS_FILE_NAME
        self.backups_dir = self.config_dir / BACKUPS_DIR_NAME
        self.profiles: dict[str, dict] = {}
        self.settings: dict = default_settings()
        self.warnings: list[str] = []

    # -- filesystem helpers -------------------------------------------------
    def ensure_dirs(self) -> None:
        ensure_dir(self.profiles_dir)
        ensure_dir(self.backups_dir)

    def _profile_path(self, profile_id: str) -> Path:
        return self.profiles_dir / f"{_ID_SANITIZE_RE.sub('-', slugify(profile_id, 'profile')).strip('-') or 'profile'}.json"

    # -- loading ------------------------------------------------------------
    def load(self) -> list[str]:
        """Load everything from disk; returns warnings (never raises)."""
        self.warnings = []
        self.ensure_dirs()
        self.settings = self._load_settings()
        self.profiles = {}
        for path in sorted(self.profiles_dir.glob("*.json")):
            if ".corrupt-" in path.name or path.name.endswith(".bak"):
                continue
            data, error = load_json_or_quarantine(path)
            if error:
                self.warnings.append(error)
            if not isinstance(data, dict):
                if data is not None:
                    self.warnings.append(f"{path.name} does not contain an object; ignored")
                continue
            problems = validate_profile(data)
            profile = sanitize_profile(data, profile_id=path.stem)
            if problems:
                # Repair silently but keep the original as .bak of the rewrite.
                self.warnings.append(
                    f"{path.name} had problems and was repaired: "
                    + "; ".join(problems[:3])
                )
            self.profiles[profile["id"]] = profile

        if not self.profiles:
            profile = new_profile(DEFAULT_PROFILE_NAME, DEFAULT_PROFILE_NAME.lower())
            self.profiles[profile["id"]] = profile
            self._write_profile(profile)
            self.warnings.append("no valid profiles found - created the default profile")

        if self.settings.get("active_profile") not in self.profiles:
            self.settings["active_profile"] = next(iter(self.profiles))
            self._save_settings()
        return self.warnings

    def _load_settings(self) -> dict:
        data, error = load_json_or_quarantine(self.settings_path)
        if error:
            self.warnings.append(error)
        if data is None:
            data = {}
        return sanitize_settings(data)

    # -- profiles -----------------------------------------------------------
    def list_profiles(self) -> list[tuple[str, str]]:
        """``[(id, display name), ...]`` sorted by name."""
        return sorted(
            ((pid, profile["name"]) for pid, profile in self.profiles.items()),
            key=lambda item: item[1].lower(),
        )

    def get(self, profile_id: str | None = None) -> dict:
        pid = profile_id or self.active_profile_id
        if pid not in self.profiles:
            raise ProfileError(f"unknown profile: {pid!r}")
        return self.profiles[pid]

    @property
    def active_profile_id(self) -> str:
        return self.settings.get("active_profile", "")

    @property
    def active_profile(self) -> dict:
        return self.get(self.active_profile_id)

    def button(self, slot: int) -> dict:
        profile = self.active_profile
        for button in profile["buttons"]:
            if button["slot"] == slot:
                return button
        raise ProfileError(f"no button at slot {slot}")

    def set_button(self, slot: int, button: dict, profile_id: str | None = None) -> None:
        profile = self.get(profile_id)
        clean = sanitize_button_for_slot(button, slot)
        replaced = False
        for index, existing in enumerate(profile["buttons"]):
            if existing["slot"] == slot:
                profile["buttons"][index] = clean
                replaced = True
                break
        if not replaced:
            profile["buttons"].append(clean)
            profile["buttons"].sort(key=lambda entry: entry["slot"])
        self.save_profile(profile["id"])

    def set_profile_name(self, profile_id: str, name: str) -> None:
        profile = self.get(profile_id)
        clean = str(name).strip()
        if not clean:
            raise ProfileError("profile name must not be empty")
        profile["name"] = clean[:60]
        self.save_profile(profile_id)

    def _unique_id(self, base: str) -> str:
        candidate = slugify(base, "profile")
        if candidate not in self.profiles:
            return candidate
        counter = 2
        while f"{candidate}-{counter}" in self.profiles:
            counter += 1
        return f"{candidate}-{counter}"

    def create_profile(self, name: str) -> str:
        clean = str(name).strip() or "Profile"
        pid = self._unique_id(clean)
        profile = new_profile(clean, pid)
        profile["id"] = pid
        self.profiles[pid] = profile
        self._write_profile(profile)
        log.info("created profile %r (%s)", profile["name"], pid)
        return pid

    def duplicate_profile(self, profile_id: str, name: str | None = None) -> str:
        source = self.get(profile_id)
        clean = (name or f"{source['name']} copy").strip()
        pid = self._unique_id(clean)
        import copy as _copy

        clone = _copy.deepcopy(source)
        clone["id"] = pid
        clone["name"] = clean[:60]
        clone["created"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        self.profiles[pid] = clone
        self._write_profile(clone)
        log.info("duplicated profile %r as %r", source["name"], clone["name"])
        return pid

    def rename_profile(self, profile_id: str, name: str) -> str:
        """Rename a profile; the file name (id) stays stable."""
        profile = self.get(profile_id)
        clean = str(name).strip()
        if not clean:
            raise ProfileError("profile name must not be empty")
        profile["name"] = clean[:60]
        self.save_profile(profile_id)
        return profile_id

    def delete_profile(self, profile_id: str) -> None:
        if profile_id not in self.profiles:
            raise ProfileError(f"unknown profile: {profile_id!r}")
        if len(self.profiles) <= 1:
            raise ProfileError("the last remaining profile cannot be deleted")
        profile = self.profiles.pop(profile_id)
        try:
            self._profile_path(profile_id).unlink()
        except OSError as exc:
            log.warning("could not remove profile file: %s", exc)
        log.info("deleted profile %r", profile["name"])
        if self.active_profile_id == profile_id:
            self.settings["active_profile"] = next(iter(self.profiles))
            self._save_settings()

    def save_profile(self, profile_id: str) -> None:
        profile = self.get(profile_id)
        problems = validate_profile(profile)
        if problems:
            raise ProfileError("refusing to save an invalid profile: " + "; ".join(problems[:4]))
        self._write_profile(profile)

    def _write_profile(self, profile: dict) -> None:
        try:
            write_json(self._profile_path(profile["id"]), profile)
        except Exception as exc:  # disk full / permissions
            log.error("failed saving profile %s: %s", profile["id"], exc)
            raise ProfileError(f"could not save profile {profile['name']!r}: {exc}") from exc

    # -- active profile / settings -----------------------------------------
    def set_active(self, profile_id: str) -> None:
        if profile_id not in self.profiles:
            raise ProfileError(f"unknown profile: {profile_id!r}")
        self.settings["active_profile"] = profile_id
        self._save_settings()

    def update_settings(self, **updates: Any) -> dict:
        """Shallow-merge ``updates`` into known settings keys and persist."""
        serial_updates = updates.pop("serial", None)
        for key, value in updates.items():
            if key in self.settings and key != "active_profile":
                self.settings[key] = value
            elif key in self.settings:
                self.settings[key] = value
        if isinstance(serial_updates, dict):
            merged = sanitize_settings(
                {**self.settings, "serial": {**self.settings["serial"], **serial_updates}}
            )
            self.settings = merged
        self._save_settings()
        return self.settings

    def _save_settings(self) -> None:
        try:
            write_json(self.settings_path, self.settings)
        except Exception as exc:
            log.error("failed saving settings: %s", exc)
            raise ProfileError(f"could not save settings: {exc}") from exc

    # -- iteration ----------------------------------------------------------
    def __iter__(self) -> Iterator[dict]:
        return iter(self.profiles.values())

    def __len__(self) -> int:
        return len(self.profiles)

    def find_profile_by_name(self, name: str) -> str | None:
        wanted = str(name).strip().lower()
        for pid, profile in self.profiles.items():
            if profile["name"].lower() == wanted:
                return pid
        return None


def sanitize_button_for_slot(button: Any, slot: int) -> dict:
    from .models import sanitize_button

    return sanitize_button(button, slot=slot)


__all__ = [
    "DEFAULT_PROFILE_NAME",
    "ProfileError",
    "ProfileStore",
    "default_config_dir",
    "default_settings",
    "sanitize_settings",
]
