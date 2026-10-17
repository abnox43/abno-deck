"""Tests for debouncing."""

from __future__ import annotations

import unittest

from src.debounce import Debouncer


class DebouncerTests(unittest.TestCase):
    def test_first_event_is_allowed(self):
        debouncer = Debouncer(200)
        self.assertTrue(debouncer.allow("b1", now=0.0))

    def test_rapid_duplicate_is_suppressed(self):
        debouncer = Debouncer(200)
        debouncer.allow("b1", now=0.0)
        self.assertFalse(debouncer.allow("b1", now=0.05))
        self.assertFalse(debouncer.allow("b1", now=0.19))

    def test_event_after_window_is_allowed(self):
        debouncer = Debouncer(200)
        debouncer.allow("b1", now=0.0)
        self.assertTrue(debouncer.allow("b1", now=0.21))

    def test_keys_are_independent(self):
        debouncer = Debouncer(200)
        debouncer.allow(1, now=0.0)
        self.assertTrue(debouncer.allow(2, now=0.0))

    def test_zero_window_allows_everything(self):
        debouncer = Debouncer(0)
        self.assertTrue(debouncer.allow("b1", now=0.0))
        self.assertTrue(debouncer.allow("b1", now=0.0))

    def test_reset_clears_state(self):
        debouncer = Debouncer(200)
        debouncer.allow("b1", now=0.0)
        debouncer.reset("b1")
        self.assertTrue(debouncer.allow("b1", now=0.01))
        debouncer.reset()
        self.assertTrue(debouncer.allow("b1", now=0.02))

    def test_window_updates(self):
        debouncer = Debouncer(100)
        self.assertEqual(debouncer.window_ms, 100)
        debouncer.window_ms = 500
        self.assertEqual(debouncer.window_ms, 500)
        debouncer.allow("b1", now=0.0)
        self.assertFalse(debouncer.allow("b1", now=0.4))

    def test_suppressed_countdown(self):
        debouncer = Debouncer(200)
        debouncer.allow("b1", now=0.0)
        self.assertAlmostEqual(debouncer.suppressed_count("b1", now=0.05), 0.15)
        self.assertEqual(debouncer.suppressed_count("b1", now=1.0), 0.0)


if __name__ == "__main__":
    unittest.main()
