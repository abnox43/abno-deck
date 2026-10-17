"""Backup and restore of the ABNO DECK configuration directory.

A backup is a plain ZIP file containing every profile and the settings file.
Restoring validates each entry first; invalid profiles are quarantined instead
of silently overwriting good data, and the current configuration is copied
aside before anything is replaced.

Command line usage (from the installation directory)::

    python3 -m src.backup create [--output FILE]
    python3 -m src.backup restore FILE [--config-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .constants import PROFILES_DIR_NAME, SETTINGS_FILE_NAME
from .models import sanitize_profile, validate_profile
from .profiles import default_config_dir, sanitize_settings
from .storage import ensure_dir, write_json

log = logging.getLogger(__name__)

BACKUP_PREFIX = "abno-deck-backup"


class BackupError(RuntimeError):
    pass


@dataclass
class RestoreReport:
    profiles_restored: int = 0
    profiles_skipped: list[str] = field(default_factory=list)
    settings_restored: bool = False
    pre_restore_copy: Path | None = None
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"{self.profiles_restored} profile(s) restored"]
        if self.settings_restored:
            parts.append("settings restored")
        if self.profiles_skipped:
            parts.append("skipped invalid: " + ", ".join(self.profiles_skipped))
        return "; ".join(parts)


def default_backup_name() -> str:
    return f"{BACKUP_PREFIX}-{time.strftime('%Y%m%d-%H%M%S')}.zip"


def create_backup(config_dir: Path | str | None = None, destination: Path | str | None = None) -> Path:
    """Zip the configuration directory. Returns the archive path."""
    config = Path(config_dir).expanduser() if config_dir else default_config_dir()
    if destination is None:
        destination = Path.home() / default_backup_name()
    else:
        destination = Path(destination).expanduser()
    ensure_dir(destination.parent)

    if not config.exists():
        raise BackupError(f"configuration directory does not exist: {config}")

    entries = 0
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(config.rglob("*")):
            if not path.is_file():
                continue
            if ".corrupt-" in path.name or path.suffix in (".tmp", ".log") or path.name.endswith(".bak"):
                continue
            if path.suffix != ".json":
                continue
            archive.write(path, path.relative_to(config))
            entries += 1
    if entries == 0:
        raise BackupError(f"nothing to back up in {config} (no JSON files found)")
    log.info("backup written: %s (%d file(s))", destination, entries)
    return destination


def restore_backup(archive_path: Path | str, config_dir: Path | str | None = None) -> RestoreReport:
    """Restore a backup archive into the configuration directory."""
    archive_path = Path(archive_path).expanduser()
    config = Path(config_dir).expanduser() if config_dir else default_config_dir()
    if not zipfile.is_zipfile(archive_path):
        raise BackupError(f"not a valid ZIP archive: {archive_path}")

    report = RestoreReport()
    staging = config.parent / f"{config.name}-restore-staging-{int(time.time())}"
    ensure_dir(staging)

    # 1. Extract + validate into a staging directory.
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.namelist():
            if member.endswith("/") or ".." in Path(member).parts:
                continue
            name = Path(member).name
            if not name.endswith(".json"):
                continue
            try:
                raw = archive.read(member)
                data = json.loads(raw.decode("utf-8"))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                report.warnings.append(f"{member}: unreadable ({exc})")
                continue

            if name == SETTINGS_FILE_NAME:
                write_json(staging / SETTINGS_FILE_NAME, sanitize_settings(data), keep_backup=False)
                report.settings_restored = True
                continue

            if not isinstance(data, dict):
                report.profiles_skipped.append(member)
                continue
            problems = validate_profile(data)
            profile = sanitize_profile(data)
            if problems:
                report.warnings.append(f"{member}: repaired ({'; '.join(problems[:2])})")
            target = staging / f"{profile['id']}.json"
            write_json(target, profile, keep_backup=False)
            report.profiles_restored += 1

    if report.profiles_restored == 0:
        shutil.rmtree(staging, ignore_errors=True)
        raise BackupError("archive contains no usable profiles - nothing was changed")

    # 2. Keep a copy of the current configuration before replacing it.
    ensure_dir(config)
    safety = config.parent / f"{config.name}-pre-restore-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        if config.exists():
            shutil.copytree(config, safety, dirs_exist_ok=True)
            report.pre_restore_copy = safety
    except OSError as exc:
        report.warnings.append(f"could not copy the current config aside: {exc}")

    # 3. Replace profiles + settings with the validated staging content.
    profiles_dir = ensure_dir(config / PROFILES_DIR_NAME)
    for target in staging.glob("*.json"):
        if target.name == SETTINGS_FILE_NAME:
            shutil.copy2(target, config / SETTINGS_FILE_NAME)
        else:
            shutil.copy2(target, profiles_dir / target.name)
    shutil.rmtree(staging, ignore_errors=True)
    log.info("restore complete: %s", report.summary())
    return report


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="abno-deck-backup",
                                     description="Create or restore ABNO DECK configuration backups")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create a backup archive")
    create.add_argument("--output", "-o", help="destination .zip (default: ~/abno-deck-backup-<ts>.zip)")
    create.add_argument("--config-dir", help="override the configuration directory")

    restore = sub.add_parser("restore", help="restore a backup archive")
    restore.add_argument("archive", help="backup .zip to restore")
    restore.add_argument("--config-dir", help="override the configuration directory")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "create":
            path = create_backup(args.config_dir, args.output)
            print(f"Backup written to {path}")
            return 0
        report = restore_backup(args.archive, args.config_dir)
        print("Restored:", report.summary())
        for warning in report.warnings:
            print("  warning:", warning)
        if report.pre_restore_copy:
            print("Previous configuration kept at:", report.pre_restore_copy)
        return 0
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
