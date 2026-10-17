"""Action execution tests using stub executables (no real side effects).

A temporary directory is placed in front of PATH with fake ``gio``,
``xdg-open``, ``xdotool``, ``playerctl`` binaries that record their argv, so
the exact command lines ABNO DECK produces can be verified without opening a
real browser or sending real key presses.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import deps
from src.actions import execute


def make_stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class StubEnvironmentTestCase(unittest.TestCase):
    """Rebuild the PATH-based tool detection around a stub directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stub_dir = Path(self._tmp.name)
        self.output = self.stub_dir / "output.log"
        # PATH is *replaced*, not extended: nothing outside the stub directory
        # may be found, so tests can never open a real browser or send real keys.
        env = {**os.environ, "PATH": str(self.stub_dir), "XDG_SESSION_TYPE": "x11"}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        deps.reset_cache()
        self.addCleanup(deps.reset_cache)


class OpenUrlTests(StubEnvironmentTestCase):
    def test_gio_invoked_with_open_subcommand(self):
        make_stub(self.stub_dir, "gio", f'echo "gio $@" >> "{self.output}"')
        make_stub(self.stub_dir, "xdg-open", f'echo "xdg-open $@" >> "{self.output}"')
        result = execute({"type": "open_url", "url": "https://example.org/page"})
        self.assertTrue(result.ok, result.log_line())
        self.assertIn("gio", result.backend)
        logged = self.output.read_text()
        self.assertIn("gio open https://example.org/page", logged)
        self.assertNotIn("xdg-open", logged)

    def test_xdg_open_fallback_when_gio_missing(self):
        make_stub(self.stub_dir, "xdg-open", f'echo "xdg-open $@" >> "{self.output}"')
        result = execute({"type": "open_url", "url": "https://example.org"})
        self.assertTrue(result.ok, result.log_line())
        self.assertIn("xdg-open https://example.org", self.output.read_text())

    def test_failing_handler_reports_failure(self):
        make_stub(self.stub_dir, "gio", 'echo "boom" >&2; exit 3')
        result = execute({"type": "open_url", "url": "https://example.org"})
        self.assertFalse(result.ok)
        self.assertIn("boom", result.detail)


class LaunchAppTests(StubEnvironmentTestCase):
    def test_launch_runs_program_and_reports_success(self):
        make_stub(self.stub_dir, "my-stub-app",
                  f'echo "launched $@" >> "{self.output}"')
        result = execute({"type": "launch_app", "executable": "my-stub-app",
                          "arguments": '--flag "two words"'})
        self.assertTrue(result.ok, result.log_line())
        # Popen is async: give the stub a moment
        import time

        for _ in range(50):
            if self.output.exists():
                break
            time.sleep(0.05)
        logged = self.output.read_text() if self.output.exists() else ""
        self.assertIn("launched --flag two words", logged)

    def test_missing_executable_is_a_failure(self):
        result = execute({"type": "launch_app", "executable": "no-such-app-abno",
                          "arguments": ""})
        self.assertFalse(result.ok)
        self.assertIn("not found", result.detail)


class CommandTests(StubEnvironmentTestCase):
    def test_direct_execution_returns_stdout(self):
        make_stub(self.stub_dir, "my-tool", 'echo "hello from tool"; exit 0')
        result = execute({"type": "command", "command": "my-tool --flag",
                          "use_shell": False, "confirm": False})
        self.assertTrue(result.ok, result.log_line())
        self.assertIn("hello from tool", result.detail)

    def test_nonzero_exit_is_a_failure(self):
        make_stub(self.stub_dir, "my-tool", 'echo "bad news" >&2; exit 7')
        result = execute({"type": "command", "command": "my-tool",
                          "use_shell": False, "confirm": False})
        self.assertFalse(result.ok)
        self.assertIn("exit 7", result.summary)
        self.assertIn("bad news", result.detail)

    def test_shell_mode_runs_through_sh(self):
        result = execute({"type": "command",
                          "command": f'echo shell works > "{self.stub_dir}/shell.txt"',
                          "use_shell": True, "confirm": False})
        self.assertTrue(result.ok, result.log_line())
        self.assertTrue((self.stub_dir / "shell.txt").exists())


class ShortcutTests(StubEnvironmentTestCase):
    def test_xdotool_receives_normalized_combo(self):
        make_stub(self.stub_dir, "xdotool", f'echo "xdotool $@" >> "{self.output}"')
        result = execute({"type": "shortcut", "keys": "Ctrl+Alt+T"})
        self.assertTrue(result.ok, result.log_line())
        self.assertIn("xdotool key --clearmodifiers ctrl+alt+t", self.output.read_text())

    def test_failing_xdotool_is_reported(self):
        make_stub(self.stub_dir, "xdotool", 'echo "no display" >&2; exit 1')
        result = execute({"type": "shortcut", "keys": "Ctrl+T"})
        self.assertFalse(result.ok)
        self.assertIn("no display", result.detail)

    def test_no_backend_is_reported_with_install_hint(self):
        result = execute({"type": "shortcut", "keys": "Ctrl+T"})
        self.assertFalse(result.ok)
        self.assertIn("xdotool", result.detail)


class MediaTests(StubEnvironmentTestCase):
    def test_volume_up_reads_then_writes(self):
        make_stub(self.stub_dir, "playerctl",
                  'if [ "$1" = "volume" ]; then\n'
                  f'  echo "playerctl $@" >> "{self.output}"\n'
                  '  echo "0.50"\n'
                  'else\n'
                  f'  echo "playerctl $@" >> "{self.output}"\n'
                  'fi\n')
        result = execute({"type": "media", "command": "volume_up"})
        self.assertTrue(result.ok, result.log_line())
        lines = self.output.read_text().strip().splitlines()
        self.assertEqual(lines[0], "playerctl volume")
        self.assertEqual(lines[1], "playerctl volume 0.60")

    def test_play_pause_failure_is_reported(self):
        make_stub(self.stub_dir, "playerctl",
                  'echo "No players found" >&2; exit 1')
        result = execute({"type": "media", "command": "play_pause"})
        self.assertFalse(result.ok)
        self.assertIn("No players found", result.detail)

    def test_no_backend_reports_install_hint(self):
        result = execute({"type": "media", "command": "next"})
        self.assertFalse(result.ok)
        self.assertIn("playerctl", result.detail)


if __name__ == "__main__":
    unittest.main()
