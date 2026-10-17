"""Tests for profile/settings storage, recovery and CRUD rules."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.profiles import (
    DEFAULT_PROFILE_NAME,
    ProfileError,
    ProfileStore,
    default_settings,
    sanitize_settings,
)
from src.storage import read_json, write_json


class StorageHelperTests(unittest.TestCase):
    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub" / "file.json"
            write_json(path, {"a": 1})
            data, error = read_json(path)
            self.assertIsNone(error)
            self.assertEqual(data, {"a": 1})

    def test_write_creates_backup_of_previous_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.json"
            write_json(path, {"version": 1})
            write_json(path, {"version": 2})
            self.assertEqual(read_json(path)[0], {"version": 2})
            self.assertEqual(read_json(path.with_suffix(".json.bak"))[0], {"version": 1})

    def test_read_missing_file_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            data, error = read_json(Path(tmp) / "missing.json")
            self.assertIsNone(data)
            self.assertIsNone(error)

    def test_read_invalid_json_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{ not json", encoding="utf-8")
            data, error = read_json(path)
            self.assertIsNone(data)
            self.assertIn("invalid JSON", error)


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "abno-deck"
        self.store = ProfileStore(self.dir)
        self.store.load()

    def test_first_load_creates_default_profile(self):
        self.assertEqual(len(self.store), 1)
        self.assertIn(DEFAULT_PROFILE_NAME.lower(), self.store.profiles)
        profile = self.store.active_profile
        self.assertEqual(len(profile["buttons"]), 4)
        self.assertTrue((self.dir / "profiles" / "default.json").exists())
        self.assertTrue((self.dir / "settings.json").exists())

    def test_profiles_survive_a_restart(self):
        pid = self.store.create_profile("Streaming")
        self.store.set_active(pid)
        self.store.set_button(1, {"slot": 1, "name": "OBS", "icon": "🎬",
                                  "action": {"type": "launch_app", "executable": "obs"}})

        second = ProfileStore(self.dir)
        warnings = second.load()
        self.assertEqual(warnings, [])
        self.assertEqual(second.active_profile_id, pid)
        self.assertEqual(second.button(1)["name"], "OBS")
        self.assertEqual(second.button(1)["action"]["executable"], "obs")

    def test_create_rename_duplicate_delete(self):
        pid = self.store.create_profile("Work")
        self.store.set_active(pid)
        self.store.rename_profile(pid, "Work v2")
        self.assertEqual(self.store.get(pid)["name"], "Work v2")

        clone = self.store.duplicate_profile(pid)
        self.assertEqual(len(self.store), 3)
        self.assertEqual(self.store.get(clone)["buttons"][0]["action"],
                         self.store.get(pid)["buttons"][0]["action"])
        self.assertNotEqual(clone, pid)

        self.store.delete_profile(clone)
        self.assertNotIn(clone, self.store.profiles)
        self.assertFalse((self.dir / "profiles" / f"{clone}.json").exists())

    def test_duplicate_gets_unique_id(self):
        first = self.store.create_profile("Copy")
        second = self.store.create_profile("Copy")
        self.assertNotEqual(first, second)

    def test_cannot_delete_last_profile(self):
        with self.assertRaises(ProfileError):
            self.store.delete_profile(self.store.active_profile_id)

    def test_unknown_profile_operations_raise(self):
        with self.assertRaises(ProfileError):
            self.store.get("nope")
        with self.assertRaises(ProfileError):
            self.store.set_active("nope")
        with self.assertRaises(ProfileError):
            self.store.delete_profile("nope")

    def test_rename_to_empty_is_rejected(self):
        with self.assertRaises(ProfileError):
            self.store.rename_profile(self.store.active_profile_id, "   ")

    def test_active_profile_is_persisted(self):
        pid = self.store.create_profile("Second")
        self.store.set_active(pid)
        second = ProfileStore(self.dir)
        second.load()
        self.assertEqual(second.active_profile_id, pid)

    def test_corrupt_profile_is_quarantined_and_recovered(self):
        profile_path = self.dir / "profiles" / "default.json"
        profile_path.write_text("{ this is broken", encoding="utf-8")

        store = ProfileStore(self.dir)
        warnings = store.load()
        self.assertTrue(any("invalid JSON" in warning for warning in warnings))
        self.assertEqual(len(store), 1)  # rebuilt default
        self.assertTrue(list((self.dir / "profiles").glob("default.json.corrupt-*")))

    def test_partially_invalid_profile_is_repaired(self):
        broken = {
            "schema": 1,
            "id": "work",
            "name": "Work",
            "buttons": [
                {"slot": 1, "name": "A", "icon": "a", "action": {"type": "none"}},
                "garbage",
                {"slot": 3, "name": "C", "icon": "c", "action": {"type": "media", "command": "next"}},
            ],
        }
        (self.dir / "profiles").mkdir(parents=True, exist_ok=True)
        (self.dir / "profiles" / "work.json").write_text(json.dumps(broken), encoding="utf-8")

        store = ProfileStore(self.dir)
        warnings = store.load()
        profile = store.get("work")
        self.assertEqual(len(profile["buttons"]), 4)
        self.assertEqual(profile["buttons"][0]["name"], "A")
        self.assertEqual(profile["buttons"][1]["action"], {"type": "none"})
        self.assertEqual(profile["buttons"][2]["action"]["command"], "next")
        self.assertTrue(any("repaired" in warning for warning in warnings))

    def test_corrupt_settings_fall_back_to_defaults(self):
        (self.dir / "settings.json").write_text("]]]", encoding="utf-8")
        store = ProfileStore(self.dir)
        warnings = store.load()
        self.assertEqual(store.settings["serial"]["baud_rate"], 115200)
        self.assertTrue(any("settings.json" in warning for warning in warnings))

    def test_invalid_settings_values_are_sanitised(self):
        write_json(self.dir / "settings.json", {
            "log_level": "SHOUT",
            "serial": {"debounce_ms": 999999, "baud_rate": "fast", "auto_connect": "yes",
                       "port": 123},
            "window": {"width": "wide"},
        })
        store = ProfileStore(self.dir)
        store.load()
        settings = store.settings
        self.assertEqual(settings["log_level"], "INFO")
        self.assertEqual(settings["serial"]["debounce_ms"], 250)
        self.assertEqual(settings["serial"]["baud_rate"], 115200)
        # wrong types keep the safe defaults instead of being coerced
        self.assertTrue(settings["serial"]["auto_connect"])
        self.assertEqual(settings["serial"]["port"], "")
        self.assertEqual(settings["window"]["width"], 1080)

    def test_update_settings_persists(self):
        self.store.update_settings(serial={"port": "/dev/ttyUSB0", "debounce_ms": 400})
        second = ProfileStore(self.dir)
        second.load()
        self.assertEqual(second.settings["serial"]["port"], "/dev/ttyUSB0")
        self.assertEqual(second.settings["serial"]["debounce_ms"], 400)

    def test_refuses_to_save_invalid_profile(self):
        profile = self.store.active_profile
        profile["buttons"][0]["action"] = {"type": "open_url", "url": "nonsense"}
        with self.assertRaises(ProfileError):
            self.store.save_profile(profile["id"])

    def test_find_profile_by_name(self):
        self.assertEqual(self.store.find_profile_by_name("default"), DEFAULT_PROFILE_NAME.lower())
        self.assertIsNone(self.store.find_profile_by_name("missing"))


class SettingsSanitizeTests(unittest.TestCase):
    def test_defaults(self):
        settings = sanitize_settings(None)
        self.assertEqual(settings, default_settings())

    def test_partial_input_is_merged(self):
        settings = sanitize_settings({"serial": {"auto_connect": False}})
        self.assertFalse(settings["serial"]["auto_connect"])
        self.assertTrue(settings["serial"]["auto_reconnect"])


if __name__ == "__main__":
    unittest.main()
