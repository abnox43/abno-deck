"""Reading Linux ``.desktop`` entries for the application picker.

The picker offers a searchable list of installed programs by parsing the
freedesktop desktop entries from the standard directories.  Entries that are
hidden (``Hidden=true`` / ``NoDisplay=true``) are skipped, and Exec field
codes (``%f``, ``%u``...) are resolved so the resulting argument list can be
handed straight to ``subprocess`` without a shell.
"""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

DESKTOP_DIRS = (
    Path.home() / ".local" / "share" / "applications",
    Path("/usr/local/share/applications"),
    Path("/usr/share/applications"),
)

# Exec field codes that disappear from the command line.
_DROP_CODES = "%d %D %n %N %v %m %f %F %u %U".split()


@dataclass(frozen=True)
class AppEntry:
    name: str
    desktop_id: str
    exec_line: str
    argv: tuple[str, ...]
    icon: str = ""
    comment: str = ""
    keywords: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    path: str = ""

    def matches(self, needle: str) -> bool:
        if not needle:
            return True
        haystack = " ".join(
            (self.name, self.comment, " ".join(self.keywords), self.exec_line,
             self.desktop_id)
        ).lower()
        return needle.lower() in haystack


def parse_desktop_file(path: Path) -> dict[str, str]:
    """Minimal desktop entry parser: ``Key=Value`` inside ``[Desktop Entry]``."""
    entries: dict[str, str] = {}
    in_entry = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, _, value = line.partition("=")
        entries[key.strip()] = value.strip()
    return entries


def expand_exec(exec_line: str, icon: str = "", name: str = "", path: str = "") -> tuple[str, ...]:
    """Turn a desktop ``Exec=`` line into an argv tuple without field codes."""
    try:
        tokens = shlex.split(exec_line, posix=True)
    except ValueError:
        return ()

    argv: list[str] = []
    for token in tokens:
        if token == "%i" and icon:
            argv += ["--icon", icon]
            continue
        if token == "%c" and name:
            argv.append(name)
            continue
        if token == "%k" and path:
            argv.append(path)
            continue
        if "%" not in token:
            argv.append(token)
            continue
        expanded = _strip_field_codes(token)
        if expanded:
            argv.append(expanded)
    return tuple(argv)


def _strip_field_codes(token: str) -> str:
    """Remove ``%X`` field codes from a token; ``%%`` becomes a literal ``%``."""
    masked = token.replace("%%", "\x00")
    result: list[str] = []
    index = 0
    while index < len(masked):
        char = masked[index]
        if char == "%" and index + 1 < len(masked):
            index += 2  # drop the field code entirely (f F u U d D n N v m c k i)
            continue
        result.append(char)
        index += 1
    return "".join(result).replace("\x00", "%")


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("true", "1", "yes")


def _split_list(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(";") if part.strip())


def load_desktop_entries() -> list[AppEntry]:
    """Parse every visible ``.desktop`` entry (cached for the session)."""
    return _load(tuple(DESKTOP_DIRS))


@lru_cache(maxsize=4)
def _load(dirs: tuple[Path, ...]) -> list[AppEntry]:
    entries: list[AppEntry] = []
    seen_ids: set[str] = set()
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*.desktop")):
            desktop_id = path.name
            if desktop_id in seen_ids:
                continue  # user entry shadows the system one
            data = parse_desktop_file(path)
            if not data:
                continue
            if data.get("Type", "Application") != "Application":
                continue
            if _truthy(data.get("Hidden", "")) or _truthy(data.get("NoDisplay", "")):
                continue
            # Respect explicit "do not show in MATE" markers only.
            if "MATE" in _split_list(data.get("NotShowIn", "")):
                continue
            name = data.get("Name", "").strip()
            exec_line = data.get("Exec", "").strip()
            if not name or not exec_line:
                continue
            argv = expand_exec(exec_line, icon=data.get("Icon", ""), name=name,
                               path=str(path))
            if not argv:
                continue
            try_exec = data.get("TryExec", "").strip()
            if try_exec and not (os.path.exists(try_exec) if "/" in try_exec
                                 else _which_local(try_exec)):
                continue
            entries.append(
                AppEntry(
                    name=name,
                    desktop_id=desktop_id,
                    exec_line=exec_line,
                    argv=argv,
                    icon=data.get("Icon", ""),
                    comment=data.get("Comment", ""),
                    keywords=_split_list(data.get("Keywords", "")),
                    categories=_split_list(data.get("Categories", "")),
                    path=str(path),
                )
            )
            seen_ids.add(desktop_id)
    entries.sort(key=lambda entry: entry.name.lower())
    return entries


def _which_local(command: str) -> str:
    import shutil

    return shutil.which(command) or ""


def to_exec_fields(argv: tuple[str, ...] | list[str]) -> tuple[str, str]:
    """Split an argv into ``(executable, arguments)`` for the button editor."""
    if not argv:
        return "", ""
    executable = argv[0]
    try:
        arguments = shlex.join(list(argv[1:]))
    except AttributeError:  # pragma: no cover - Python < 3.8
        arguments = " ".join(shlex.quote(part) for part in argv[1:])
    return executable, arguments


__all__ = ["AppEntry", "DESKTOP_DIRS", "expand_exec", "load_desktop_entries",
           "parse_desktop_file", "to_exec_fields"]
