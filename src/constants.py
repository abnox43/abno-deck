"""Global constants for ABNO DECK.

Everything in this module is data only: no Qt, no serial, no I/O. It is safe
to import from tests, the CLI helpers and the GUI alike.
"""

from __future__ import annotations

APP_NAME = "ABNO DECK"
APP_ID = "abno-deck"
VERSION = "1.0.0"

# --- Serial protocol -------------------------------------------------------
BAUD_RATE = 115200
READY_MARKER = "ABNODECK:READY"
BUTTON_PREFIX = "BUTTON:"
NUM_BUTTONS = 4
MIN_BUTTON = 1
MAX_BUTTON = 4

SERIAL_READ_TIMEOUT = 0.5       # seconds between read() returns (lets the loop breathe)
HANDSHAKE_TIMEOUT = 3.0         # seconds to wait for ABNODECK:READY after opening
# Opening the port toggles DTR/RTS, which resets the ESP32: everything that
# arrives in the wake of that reset (boot text, kernel-buffered backlog, boot
# pin glitches that pass a naive firmware debounce) is startup noise, not a
# deliberate user press.  Button events are therefore validated and logged but
# not dispatched until this long after the READY handshake.  Bounded and
# logged - real presses after the window flow normally.
STARTUP_IGNORE_GRACE = 0.5
CONNECT_RETRY_DELAY = 2.0       # seconds between auto-detection attempts
RECONNECT_BACKOFF_START = 1.0   # seconds after the first unexpected disconnect
RECONNECT_BACKOFF_MAX = 10.0    # never wait longer than this between attempts
DEFAULT_DEBOUNCE_MS = 250       # desktop-side safeguard against repeated events

# USB vendor IDs that are commonly used by ESP32 dev boards / USB-UART bridges.
KNOWN_USB_IDS: dict[int, str] = {
    0x10C4: "CP210x (Silicon Labs - ESP32-DevKitC)",
    0x1A86: "CH340/CH341 (WCH - many ESP32 boards)",
    0x303A: "Espressif native USB CDC",
    0x0403: "FTDI FT232/FT2232",
    0x2341: "Arduino / Espressif hybrids",
    0x1B4F: "SparkFun (Double stacked boards)",
    0x2E8A: "Raspberry Pi RP2040 (common on Pico-ESP bridges)",
}

# --- Storage ---------------------------------------------------------------
CONFIG_DIR_NAME = "abno-deck"
PROFILES_DIR_NAME = "profiles"
SETTINGS_FILE_NAME = "settings.json"
BACKUPS_DIR_NAME = "backups"
CONFIG_SCHEMA_VERSION = 1
PROFILE_SCHEMA_VERSION = 1
CONFIG_ENV_VAR = "ABNO_DECK_CONFIG_DIR"

# --- Actions ---------------------------------------------------------------
ACTION_TYPES = (
    "launch_app",
    "open_url",
    "shortcut",
    "media",
    "command",
    "none",
)

MEDIA_COMMANDS = (
    "play_pause",
    "next",
    "previous",
    "volume_up",
    "volume_down",
)

MEDIA_LABELS = {
    "play_pause": "Play / Pause",
    "next": "Next track",
    "previous": "Previous track",
    "volume_up": "Volume up",
    "volume_down": "Volume down",
}

# URL schemes we are willing to hand to the desktop default handler.
ALLOWED_URL_SCHEMES = ("http", "https")

# Shell metacharacters that require the explicit "allow shell" opt-in.
SHELL_METACHARACTERS = ("|", "&", ";", ">", "<", "$(", "`", "(", ")", "{", "}", "*", "?", "~")
