"""JSON helpers with validation, atomic writes and crash recovery.

All ABNO DECK configuration lives under ``~/.config/abno-deck`` (XDG style).
This module guarantees:

* writes are atomic (temp file + ``os.replace``) so a crash cannot truncate a
  profile,
* unreadable/invalid JSON never crashes the app: the file is quarantined as
  ``<name>.corrupt-<timestamp>`` and the caller rebuilds a default,
* a ``.bak`` copy is kept of the previous version of every file.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ENCODING = "utf-8"


class StorageError(RuntimeError):
    """Raised when a write operation fails (read failures are recovered)."""


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path) -> tuple[Any | None, str | None]:
    """Read a JSON file.

    Returns ``(data, None)`` on success or ``(None, error_message)`` on any
    problem.  Never raises for missing/corrupt files.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding=ENCODING)
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"cannot read {path.name}: {exc}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON in {path.name}: {exc.msg} (line {exc.lineno})"
    except UnicodeDecodeError:
        return None, f"{path.name} is not valid UTF-8"


def write_json(path: Path, data: Any, *, keep_backup: bool = True) -> None:
    """Atomically write ``data`` as pretty printed JSON."""
    path = Path(path)
    ensure_dir(path.parent)
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n"

    if keep_backup and path.exists():
        try:
            shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
        except OSError as exc:  # a failed backup copy must not block saving
            log.warning("could not keep .bak for %s: %s", path, exc)

    tmp_name: str | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name, suffix=".tmp"
        )
        with os.fdopen(fd, "w", encoding=ENCODING) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    except OSError as exc:
        raise StorageError(f"cannot write {path}: {exc}") from exc
    finally:
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass


def quarantine(path: Path) -> Path | None:
    """Move a broken file aside so it can be inspected instead of deleted."""
    path = Path(path)
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
    counter = 1
    while target.exists():
        target = path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}-{counter}")
        counter += 1
    try:
        os.replace(path, target)
    except OSError as exc:
        log.warning("could not quarantine %s: %s", path, exc)
        return None
    return target


def load_json_or_quarantine(path: Path) -> tuple[Any | None, str | None]:
    """``read_json`` but broken files are quarantined automatically."""
    data, error = read_json(path)
    if error is None:
        return data, None
    moved = quarantine(path)
    if moved is not None:
        error = f"{error}; the broken file was moved to {moved.name}"
    return None, error


__all__ = [
    "ENCODING",
    "StorageError",
    "ensure_dir",
    "load_json_or_quarantine",
    "quarantine",
    "read_json",
    "write_json",
]
