"""Tests for the backup/restore feature and action dispatch."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.actions import execute, validate
from src.backup import BackupError, create_backup, restore_backup
from src.profiles import ProfileStore


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup
                        )
        self.root = Path(self._tmp.name)
        self.config = self.root / "config"
        self.store = ProfileStore(self.config)
        self.store.load()

    def test_create_and_restore_roundtrip(self):
        pid = self.store.create_profile("Streaming")
        self.store.set_button(1, {"slot": 1, "name": "OBS", "icon": "🎬",
                                  "action": {"type": "launch_app", "executable": "obs"}},
                              profile_id=pid)

        archive = create_backup(self.config, self.root / "backup.zip")
        self.assertTrue(archive.exists())

        # destroy local state
        self.store.delete_profile(pid)
        self.assertEqual(len(self.store), 1)

        report = restore_backup(archive, self.config)
        self.assertGreaterEqual(report.profiles_restored, 2)

        restored = ProfileStore(self.config)
        restored.load()
        self.assertIn(pid, restored.profiles)
        self.assertEqual(restored.get(pid)["buttons"][0]["name"], "OBS")

    def test_restore_keeps_pre_restore_copy(self):
        archive = create_backup(self.config, self.root / "backup2.zip")
        report = restore_backup(archive, self.config)
        self.assertIsNotNone(report.pre_restore_copy)
        self.assertTrue(report.pre_restore_copy.exists())

    def test_restore_rejects_non_zip(self):
        bogus = self.root / "not-a-zip.zip"
        bogus.write_text("hello", encoding="utf-8")
        with self.assertRaises(BackupError):
            restore_backup(bogus, self.config)

    def test_restore_rejects_archive_without_profiles(self):
        import zipfile

        empty = self.root / "empty.zip"
        with zipfile.ZipFile(empty, "w") as archive:
            archive.writestr("readme.txt", "nothing here")
        with self.assertRaises(BackupError):
            restore_backup(empty, self.config)

    def test_restore_repairs_invalid_profiles(self):
        import zipfile

        mixed = self.root / "mixed.zip"
        good = json.dumps({
            "schema": 1, "id": "good", "name": "Good",
            "buttons": [{"slot": i, "name": f"B{i}", "icon": "x",
                         "action": {"type": "none"}} for i in range(1, 5)],
        })
        with zipfile.ZipFile(mixed, "w") as archive:
            archive.writestr("profiles/good.json", good)
            archive.writestr("profiles/bad.json", "{ broken")
        report = restore_backup(mixed, self.config)
        self.assertEqual(report.profiles_restored, 1)
        self.assertTrue(any("unreadable" in warning for warning in report.warnings))

    def test_backup_of_missing_dir_fails_cleanly(self):
        with self.assertRaises(BackupError):
            create_backup(self.root / "does-not-exist", self.root / "x.zip")


class ActionDispatchTests(unittest.TestCase):
    """Execution tests only where the failure is guaranteed and side effect free."""

    def test_validate_delegates(self):
        self.assertEqual(validate({"type": "none"}), [])
        self.assertTrue(validate({"type": "media", "command": "eject"}))

    def test_execute_none(self):
        result = execute({"type": "none"})
        self.assertTrue(result.ok)

    def test_execute_unknown_type(self):
        result = execute({"type": "launch_missile"})
        self.assertFalse(result.ok)

    def test_execute_garbage_input(self):
        for garbage in (None, "string", 42, [], {"type": 123}):
            result = execute(garbage)
            self.assertFalse(result.ok, garbage)

    def test_execute_missing_executable_reports_failure(self):
        result = execute({"type": "launch_app",
                          "executable": "definitely-not-installed-abno-deck",
                          "arguments": ""})
        self.assertFalse(result.ok)
        self.assertIn("not found", result.detail)

    def test_execute_invalid_url_reports_failure(self):
        result = execute({"type": "open_url", "url": "gopher://old.school"})
        self.assertFalse(result.ok)

    def test_execute_command_with_missing_program_refused(self):
        result = execute({"type": "command",
                          "command": "definitely-not-installed-abno-deck --flag",
                          "use_shell": False, "confirm": True})
        self.assertFalse(result.ok)

    def test_execute_command_shell_metacharacters_without_opt_in(self):
        result = execute({"type": "command",
                          "command": "echo hi > /tmp/abno-deck-should-not-exist",
                          "use_shell": False, "confirm": False})
        self.assertFalse(result.ok)

    def test_execute_invalid_shortcut(self):
        result = execute({"type": "shortcut", "keys": ""})
        self.assertFalse(result.ok)

    def test_execute_invalid_media_command(self):
        result = execute({"type": "media", "command": "eject"})
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
