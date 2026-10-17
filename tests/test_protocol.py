"""Tests for the strict serial protocol parser."""

from __future__ import annotations

import unittest

from src.constants import READY_MARKER
from src.protocol import MessageKind, is_protocol_line, parse_line


class ReadyMessageTests(unittest.TestCase):
    def test_ready_with_lf(self):
        message = parse_line(READY_MARKER + "\n")
        self.assertTrue(message.is_ready)
        self.assertEqual(message.kind, MessageKind.READY)

    def test_ready_with_crlf(self):
        self.assertTrue(parse_line(READY_MARKER + "\r\n").is_ready)

    def test_ready_without_terminator(self):
        self.assertTrue(parse_line(READY_MARKER).is_ready)

    def test_ready_with_surrounding_spaces(self):
        self.assertTrue(parse_line("  " + READY_MARKER + "  ").is_ready)

    def test_ready_with_extra_text_is_rejected(self):
        message = parse_line(READY_MARKER + " extra")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)
        self.assertIn("unrecognised", message.reason)

    def test_ready_is_case_sensitive(self):
        self.assertEqual(parse_line("abnodeck:ready").kind, MessageKind.UNKNOWN)


class ButtonMessageTests(unittest.TestCase):
    def test_buttons_one_to_four(self):
        for number in (1, 2, 3, 4):
            message = parse_line(f"BUTTON:{number}\n")
            self.assertTrue(message.is_button, number)
            self.assertEqual(message.button, number)

    def test_button_with_crlf(self):
        message = parse_line("BUTTON:3\r\n")
        self.assertEqual(message.button, 3)

    def test_button_with_spaces(self):
        message = parse_line("  BUTTON:2\t\n")
        self.assertEqual(message.button, 2)

    def test_button_zero_is_rejected(self):
        message = parse_line("BUTTON:0")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)
        self.assertIn("outside supported range", message.reason)

    def test_button_five_is_rejected(self):
        message = parse_line("BUTTON:5")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)

    def test_button_large_number_is_rejected(self):
        message = parse_line("BUTTON:99")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)

    def test_button_with_text_suffix_is_rejected(self):
        message = parse_line("BUTTON:1 rm -rf /")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)
        self.assertIn("malformed", message.reason)

    def test_button_prefix_without_number_is_rejected(self):
        message = parse_line("BUTTON:")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)

    def test_button_alpha_is_rejected(self):
        self.assertEqual(parse_line("BUTTON:A").kind, MessageKind.UNKNOWN)

    def test_never_interprets_arbitrary_commands(self):
        for line in ("sudo reboot", "sh -c 'echo pwned'", "EXEC:format",
                     "{'type': 'command'}", "BUTTON:1; DROP TABLE"):
            message = parse_line(line)
            self.assertEqual(message.kind, MessageKind.UNKNOWN, line)
            self.assertFalse(is_protocol_line(line), line)


class EdgeCaseTests(unittest.TestCase):
    def test_empty_and_none(self):
        self.assertEqual(parse_line("").kind, MessageKind.EMPTY)
        self.assertEqual(parse_line("\n\r\n").kind, MessageKind.EMPTY)
        self.assertEqual(parse_line(None).kind, MessageKind.EMPTY)

    def test_bytes_input(self):
        self.assertEqual(parse_line(b"BUTTON:4\n").button, 4)
        self.assertTrue(parse_line((READY_MARKER + "\r\n").encode()).is_ready)

    def test_invalid_utf8_bytes_do_not_raise(self):
        message = parse_line(b"\xff\xfe garbage \x00\n")
        self.assertEqual(message.kind, MessageKind.UNKNOWN)

    def test_raw_is_preserved(self):
        raw = "BUTTON:1\r\n"
        self.assertEqual(parse_line(raw).raw, raw)

    def test_is_protocol_line_positive_cases(self):
        self.assertTrue(is_protocol_line("BUTTON:2"))
        self.assertTrue(is_protocol_line(READY_MARKER))


if __name__ == "__main__":
    unittest.main()
