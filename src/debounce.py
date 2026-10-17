"""Desktop-side event debouncing.

The ESP32 firmware should already debounce its own buttons, but the desktop
adds a second safeguard so a bouncing switch (or a stuck/flooding device) can
never trigger an action dozens of times per second.

The class is pure Python with an injectable clock, which keeps it unit
testable without sleeping.
"""

from __future__ import annotations

import time
from typing import Callable, Hashable

from .constants import DEFAULT_DEBOUNCE_MS


class Debouncer:
    """Return ``False`` when the same key fired less than ``window`` ago."""

    def __init__(
        self,
        window_ms: int = DEFAULT_DEBOUNCE_MS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window_s = max(0.0, float(window_ms) / 1000.0)
        self._clock = clock
        self._last: dict[Hashable, float] = {}

    # -- properties ---------------------------------------------------------
    @property
    def window_ms(self) -> int:
        return int(round(self._window_s * 1000))

    @window_ms.setter
    def window_ms(self, value: int) -> None:
        self._window_s = max(0.0, float(value) / 1000.0)

    # -- API ----------------------------------------------------------------
    def allow(self, key: Hashable, now: float | None = None) -> bool:
        """Record an event for ``key``; ``True`` if it should be processed."""
        if self._window_s <= 0:
            return True
        timestamp = self._clock() if now is None else now
        previous = self._last.get(key)
        self._last[key] = timestamp
        if previous is None:
            return True
        return (timestamp - previous) >= self._window_s

    def reset(self, key: Hashable | None = None) -> None:
        """Forget state for one key (or everything when ``key`` is ``None``)."""
        if key is None:
            self._last.clear()
        else:
            self._last.pop(key, None)

    def suppressed_count(self, key: Hashable, now: float | None = None) -> float:
        """Seconds still remaining before ``key`` may fire again (0.0 if ready)."""
        if self._window_s <= 0:
            return 0.0
        timestamp = self._clock() if now is None else now
        previous = self._last.get(key)
        if previous is None:
            return 0.0
        remaining = self._window_s - (timestamp - previous)
        return remaining if remaining > 0 else 0.0


__all__ = ["Debouncer"]
