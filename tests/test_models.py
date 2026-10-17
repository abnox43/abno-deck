"""Tests for action/button validation and profile sanitising."""

from __future__ import annotations

import unittest

from src.models import (
    contains_shell_metacharacters,
    default_buttons,
    describe_action,
    new_button,
    new_profile,
    parse_shortcut,
    parse_url,
    sanitize_action,
    sanitize_button,
    sanitize_profile,
    slugify,
    validate_action,
    validate_button,
    validate_profile,
)


class ActionValidationTests(unittest.TestCase):
    def test_valid_launch_app(self):
        action = {"type": "launch_app", "executable": "x-terminal-emulator", "arguments": "-x"}
        self.assertEqual(validate_action(action), [])

    def test_launch_app_requires_executable(self):
        errors = validate_action({"type": "launch_app", "executable": ""})
        self.assertTrue(any("executable" in error for error in errors))

    def test_launch_app_rejects_arguments_in_executable(self):
        errors = validate_action({"type": "launch_app", "executable": "ls -la /"})
        self.assertTrue(any("single program" in error for error in errors))

    def test_open_url_valid_and_invalid(self):
        self.assertEqual(validate_action({"type": "open_url", "url": "https://a.b/c"}), [])
        self.assertTrue(validate_action({"type": "open_url", "url": "ftp://x"}))
        self.assertTrue(validate_action({"type": "open_url", "url": "javascript:alert(1)"}))
        self.assertTrue(validate_action({"type": "open_url", "url": "example.org"}))

    def test_parse_url(self):
        self.assertEqual(parse_url("https://Example.org/x"), ("https", "Example.org/x"))
        self.assertIsNone(parse_url("nope"))

    def test_shortcut_valid_and_invalid(self):
        self.assertEqual(validate_action({"type": "shortcut", "keys": "Ctrl+Alt+T"}), [])
        self.assertEqual(validate_action({"type": "shortcut", "keys": "F13"}), [])
        self.assertTrue(validate_action({"type": "shortcut", "keys": ""}))
        self.assertTrue(validate_action({"type": "shortcut", "keys": "Ctrl+"}))
        self.assertTrue(validate_action({"type": "shortcut", "keys": "Hyper+Meta+Key"}))
        self.assertTrue(validate_action({"type": "shortcut", "keys": "Ctrl+Alt+T; rm -rf"}))

    def test_parse_shortcut_normalises(self):
        modifiers, key = parse_shortcut("Control+Alt+T")  # type: ignore[misc]
        self.assertEqual(modifiers, ["ctrl", "alt"])
        self.assertEqual(key, "t")
        modifiers, key = parse_shortcut("Meta+Space")  # type: ignore[misc]
        self.assertEqual(modifiers, ["super"])
        self.assertEqual(key, "space")
        self.assertIsNone(parse_shortcut("Ctrl+Alt+"))
        self.assertIsNone(parse_shortcut("a+b+c+d+e"))

    def test_media_validation(self):
        self.assertEqual(validate_action({"type": "media", "command": "play_pause"}), [])
        for command in ("next", "previous", "volume_up", "volume_down"):
            self.assertEqual(validate_action({"type": "media", "command": command}), [])
        self.assertTrue(validate_action({"type": "media", "command": "eject"}))
        self.assertTrue(validate_action({"type": "media", "command": ""}))

    def test_command_validation_requires_explicit_shell_opt_in(self):
        dangerous = {"type": "command", "command": "echo a > /tmp/x", "use_shell": False}
        errors = validate_action(dangerous)
        self.assertTrue(any("shell operators" in error for error in errors))
        dangerous["use_shell"] = True
        self.assertEqual(validate_action(dangerous), [])

    def test_command_empty_is_invalid(self):
        self.assertTrue(validate_action({"type": "command", "command": ""}))

    def test_contains_shell_metacharacters(self):
        for line in ("ls | wc", "a && b", "x > y", "echo $(id)", "echo `id`", "a; b"):
            self.assertTrue(contains_shell_metacharacters(line), line)
        self.assertFalse(contains_shell_metacharacters("playerctl play-pause"))

    def test_unknown_type_is_invalid(self):
        self.assertTrue(validate_action({"type": "drop_table"}))
        self.assertTrue(validate_action("not a dict"))  # type: ignore[arg-type]

    def test_none_action_always_valid(self):
        self.assertEqual(validate_action({"type": "none"}), [])

    def test_sanitize_action_normalises(self):
        self.assertEqual(sanitize_action({"type": "MEDIA", "command": "Next"})["command"], "next")
        self.assertEqual(sanitize_action({"type": "evil"}), {"type": "none"})
        self.assertEqual(sanitize_action(None), {"type": "none"})
        action = sanitize_action({"type": "command", "command": "ls", "confirm": "yes"})
        self.assertTrue(action["confirm"])
        self.assertFalse(action["use_shell"])

    def test_describe_action(self):
        self.assertIn("Launch", describe_action({"type": "launch_app", "executable": "ls"}))
        self.assertIn("Ctrl+Alt+T", describe_action({"type": "shortcut", "keys": "Ctrl+Alt+T"}))
        self.assertEqual(describe_action({"type": "none"}), "No action")


class ButtonValidationTests(unittest.TestCase):
    def test_default_button_is_valid(self):
        button = new_button(1, "Test", "🖥️", {"type": "none"})
        self.assertEqual(validate_button(button), [])

    def test_button_requires_name_and_icon(self):
        button = {"slot": 1, "name": "  ", "icon": "", "action": {"type": "none"}}
        errors = validate_button(button)
        self.assertTrue(any("name" in error for error in errors))
        self.assertTrue(any("icon" in error for error in errors))

    def test_slot_range_checked(self):
        button = {"slot": 9, "name": "x", "icon": "y", "action": {"type": "none"}}
        self.assertTrue(any("slot" in error for error in validate_button(button)))

    def test_sanitize_button_enforces_slot_and_defaults(self):
        button = sanitize_button({"name": "A", "icon": "b", "action": {"type": "nope"}}, slot=3)
        self.assertEqual(button["slot"], 3)
        self.assertEqual(button["action"], {"type": "none"})
        self.assertEqual(sanitize_button(None, slot=2)["slot"], 2)


class ProfileTests(unittest.TestCase):
    def test_default_buttons_have_four_slots(self):
        buttons = default_buttons()
        self.assertEqual([b["slot"] for b in buttons], [1, 2, 3, 4])
        for button in buttons:
            self.assertEqual(validate_button(button), [])

    def test_new_profile_is_valid(self):
        profile = new_profile("My Profile")
        self.assertEqual(validate_profile(profile), [])
        self.assertEqual(profile["id"], "my-profile")

    def test_sanitize_profile_repairs_missing_buttons(self):
        profile = sanitize_profile({"name": "Broken", "id": "broken", "buttons": []})
        self.assertEqual(len(profile["buttons"]), 4)
        self.assertEqual(validate_profile(profile), [])

    def test_sanitize_profile_handles_garbage(self):
        profile = sanitize_profile(["not", "an", "object"])
        self.assertEqual(len(profile["buttons"]), 4)
        self.assertEqual(validate_profile(profile), [])

    def test_sanitize_profile_fixes_duplicate_slots(self):
        profile = sanitize_profile({
            "name": "Dup", "id": "dup",
            "buttons": [
                {"slot": 1, "name": "A", "icon": "a", "action": {"type": "none"}},
                {"slot": 1, "name": "B", "icon": "b", "action": {"type": "none"}},
                {"name": "C", "icon": "c", "action": {"type": "none"}},
            ],
        })
        slots = [button["slot"] for button in profile["buttons"]]
        self.assertEqual(sorted(slots), [1, 2, 3, 4])
        names = [button["name"] for button in profile["buttons"]]
        self.assertIn("A", names)
        self.assertIn("B", names)

    def test_validate_profile_reports_problems(self):
        errors = validate_profile({"name": "", "id": "", "buttons": []})
        self.assertTrue(any("name" in error for error in errors))
        self.assertTrue(any("exactly 4" in error for error in errors))

    def test_slugify(self):
        self.assertEqual(slugify("Web Browser 2!"), "web-browser-2")
        self.assertEqual(slugify("   "), "profile")
        self.assertEqual(slugify("../etc/passwd"), "etc-passwd")


if __name__ == "__main__":
    unittest.main()
