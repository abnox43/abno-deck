"""Tests for serial port discovery and desktop entry parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.desktop_entries import expand_exec, parse_desktop_file, to_exec_fields
from src.ports import PortInfo, detect_ports, find_port, suggest_port


class PortDiscoveryTests(unittest.TestCase):
    def test_detect_ports_never_raises(self):
        ports = detect_ports()
        self.assertIsInstance(ports, list)
        for info in ports:
            self.assertTrue(info.device.startswith("/dev/"))

    def test_suggest_port_returns_device_or_none(self):
        suggestion = suggest_port()
        self.assertTrue(suggestion is None or suggestion.startswith("/dev/"))

    def test_suggest_port_ignores_hardware_uarts(self):
        from unittest import mock

        from src.ports import PortInfo

        hardware_only = [
            PortInfo(device="/dev/ttyS0", description="n/a"),
            PortInfo(device="/dev/ttyS1", description="n/a"),
        ]
        with mock.patch("src.ports.detect_ports", return_value=hardware_only):
            self.assertIsNone(suggest_port(),
                              "hardware UARTs must never be auto-selected")

        with_usb = hardware_only + [
            PortInfo(device="/dev/ttyUSB0", description="CP2102 USB to UART",
                     vid=0x10C4, candidate=True),
        ]
        with mock.patch("src.ports.detect_ports", return_value=with_usb):
            self.assertEqual(suggest_port(), "/dev/ttyUSB0")

    def test_find_port(self):
        self.assertIsNone(find_port("/dev/definitely-not-here"))
        ports = detect_ports()
        if ports:
            self.assertEqual(find_port(ports[0].device).device, ports[0].device)

    def test_labels_and_hints(self):
        esp = PortInfo(device="/dev/ttyUSB0", description="CP2102 USB to UART",
                       vid=0x10C4, pid=0xEA60, candidate=True)
        label = esp.label()
        self.assertIn("/dev/ttyUSB0", label)
        self.assertIn("10C4:EA60", label)
        self.assertIn("CP210x", label)
        unknown = PortInfo(device="/dev/ttyS0")
        self.assertEqual(unknown.label(), "/dev/ttyS0")
        self.assertEqual(unknown.usb_id, "")


class DesktopEntryTests(unittest.TestCase):
    def test_expand_exec_field_codes(self):
        argv = expand_exec("env FOO=1 myapp --flag %U", name="My App")
        self.assertEqual(argv, ("env", "FOO=1", "myapp", "--flag"))
        argv = expand_exec("myapp %i %c", icon="app-icon", name="My App")
        self.assertEqual(argv, ("myapp", "--icon", "app-icon", "My App"))
        self.assertEqual(expand_exec("myapp 100%%done")[1], "100%done")

    def test_expand_exec_handles_quotes(self):
        self.assertEqual(expand_exec('myapp --title "Hello World"'),
                         ("myapp", "--title", "Hello World"))

    def test_parse_desktop_file(self):
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Example App\n"
            "Exec=example %f\n"
            "Icon=example\n"
            "Keywords=foo;bar;\n"
            "\n"
            "[Desktop Action new]\n"
            "Exec=example --new\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "example.desktop"
            path.write_text(content, encoding="utf-8")
            data = parse_desktop_file(path)
        self.assertEqual(data["Name"], "Example App")
        self.assertEqual(data["Exec"], "example %f")  # actions section ignored
        self.assertEqual(data["Keywords"], "foo;bar;")

    def test_parse_missing_file(self):
        self.assertEqual(parse_desktop_file(Path("/nonexistent/x.desktop")), {})

    def test_to_exec_fields(self):
        executable, arguments = to_exec_fields(("myapp", "--new-tab", "https://x"))
        self.assertEqual(executable, "myapp")
        self.assertEqual(arguments, "--new-tab https://x")
        self.assertEqual(to_exec_fields(()), ("", ""))


if __name__ == "__main__":
    unittest.main()
