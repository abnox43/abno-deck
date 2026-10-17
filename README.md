ABNO DECK
MADE BY ME
the esp wiring 
all four buttons share the same GND pin!
ESP32 pin	Connect to
GPIO 18	Button 1
GPIO 19	Button 2
GPIO 21	Button 3
GPIO 22	Button 4
GND	One side of ALL four buttons

/*


const int buttons[] = {18, 19, 21, 22};
const int buttonCount = 4;

int lastReading[buttonCount] = {HIGH, HIGH, HIGH, HIGH};
int stableState[buttonCount] = {HIGH, HIGH, HIGH, HIGH};
unsigned long lastChange[buttonCount] = {0, 0, 0, 0};

const unsigned long debounceMs = 35;

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < buttonCount; i++) {
    pinMode(buttons[i], INPUT_PULLUP);
  }

  delay(300);
  Serial.println("ABNODECK:READY");
}

void loop() {
  unsigned long now = millis();

  for (int i = 0; i < buttonCount; i++) {
    int reading = digitalRead(buttons[i]);

    if (reading != lastReading[i]) {
      lastChange[i] = now;
      lastReading[i] = reading;
    }

    if ((now - lastChange[i]) >= debounceMs &&
        reading != stableState[i]) {
      stableState[i] = reading;

      // INPUT_PULLUP means LOW = pressed.
      if (stableState[i] == LOW) {
        Serial.print("BUTTON:");
        Serial.println(i + 1);
      }
    }
  }
} '


*/


A DIY 4-key stream deck for Linux + ESP32.
ABNO DECK is a desktop controller for a homemade stream deck: an ESP32 development board with four push buttons, connected over USB. Pressing a physical key launches applications, opens websites, sends keyboard shortcuts, controls media or runs a validated command — and the on-screen deck shows exactly what each key does.
Python 3 · PySide6 GUI · pyserial · JSON configuration
Designed for Debian 13 (trixie) and the MATE desktop (X11 and Wayland)
No Windows, no Electron, no cloud, no paid APIs, no telemetry
The GUI is dark cyberpunk/CRT themed with subtle silver accents, a live event log and a 2×2 deck preview that works as a real test surface

1. How it works
ESP32 (4 buttons on GPIO 18/19/21/22)                 Debian workstation
  │  USB serial, 115200 baud                          │
  │  "ABNODECK:READY"  ←── handshake on boot          │
  │  "BUTTON:1" … "BUTTON:4" ←── press events         │
  └────────────── /dev/ttyUSB0 / ttyACM0 ─────────────┘
                   ABNO DECK (Python)
                   ├─ strict protocol parser (only IDs 1-4 are accepted)
                   ├─ profile store  ~/.config/abno-deck/*.json
                   └─ action runner  (launch / URL / shortcut / media / command)
Security model — read this once, it matters:
The ESP32 only sends button identifiers. The desktop application owns the entire action mapping; nothing received over serial is ever interpreted as a command. Unknown or malformed lines are logged and dropped.
Application launches and commands use argument lists, not a shell. Shell syntax (|, ;, >, $(…)) for custom commands requires an explicit opt-in checkbox and an optional confirmation dialog.
The app is never run as root/sudo. Serial port access is granted with the dialout group or a uaccess udev rule (see §5).
Actions run on a background thread pool, so the GUI never blocks or freezes.

2. Hardware and firmware protocol
Four push buttons wired between the GPIO pins and GND, using the ESP32's internal pull-ups:
Button	GPIO
1	GPIO18
2	GPIO19
3	GPIO21
4	GPIO22
The firmware must send UTF-8 text lines at 115200 baud:
Message	Meaning
ABNODECK:READY	Boot/reset handshake
BUTTON:1…BUTTON:4	A button was pressed
Anything else (BUTTON:0, BUTTON:9, garbage, binary noise) is rejected by the desktop parser with a log entry — ABNO DECK debounces repeat events again on the PC side as a second safeguard, auto-reconnects after unplugging, and never opens the same port twice (OS-level exclusive lock).
Startup safety — pressing keys can never fire when the app connects. Opening the serial port resets most ESP32 boards (DTR/RTS). Everything that arrives in the wake of that reset — kernel-buffered backlog from while nothing was listening, replayed state, boot pin glitches that pass a naive firmware debounce — arrives as a burst of syntactically valid BUTTON:1..4 lines. ABNO DECK therefore:
discards bytes that were already buffered in the kernel before the port was opened (logged with the byte count), including a cut-off partial line,
validates and logs every incoming line, but does not dispatch button events during a bounded startup window: READY + 0.5 s (or, if the device never sends READY, a short window after opening that the first ignored press shortens),
dispatches every validated press after the window exactly once,
keeps the reader alive through unexpected errors: the port is always released and the connection retried, so one bad line or a device reset can never stop the physical buttons permanently.

3. Installation (Debian 13)
cd abno-deck
./install.sh --extras
install.sh installs for your user only:
Python dependencies from Debian packages (python3-pyserial, python3-pyside6.*) — with an automatic virtualenv+pip fallback if the packages are unavailable,
the application in ~/.local/share/abno-deck/,
a launcher at ~/.local/bin/abno-deck,
a menu entry (abno-deck.desktop) and icon,
start-at-login via ~/.config/autostart/ (disable with --no-autostart),
with --extras: xdotool (keyboard shortcuts), playerctl (media) and xdg-utils.
Useful flags:
./install.sh --dialout      # add your user to the dialout group (serial access)
./install.sh --udev         # install the uaccess udev rule instead (see §5)
./install.sh --auto-launch  # opt-in: start the GUI when the ESP32 is plugged in
./install.sh --no-deps      # skip apt (dependencies already present)
./install.sh --no-autostart # do not start ABNO DECK at desktop login
Run without installing
sudo apt install python3-pyserial python3-pyside6.qtwidgets \
                 python3-pyside6.qtgui python3-pyside6.qtcore xdotool playerctl
cd abno-deck
python3 main.py
Launch after installing
abno-deck                 # from a terminal
# or: Applications → Accessories → ABNO DECK
abno-deck --doctor        # environment report (ports, deps, profiles)

4. First run
Plug the ESP32 in. ABNO DECK auto-detects common ESP32 USB bridges (CP210x, CH340, native CDC, FTDI) and connects at 115200 baud. The header indicator shows DISCONNECTED → CONNECTING → CONNECTED and the event log shows the ABNODECK:READY handshake.
The default profile contains four working example keys: Terminal (x-terminal-emulator), Web (opens the default browser), Play/Pause (MPRIS) and Lock (Ctrl+Alt+L).
Click any on-screen key to test its action; click the ⚙ button on a key to configure it. Physical presses appear in the log with a phosphor flash on the matching key.
Use the profile selector to create, rename, duplicate or delete profiles. Every change is saved immediately — there is no "Save" button to forget.
Import the bundled sample profile:
cp ~/.local/share/abno-deck/app/sample-profile.json \
   ~/.config/abno-deck/profiles/sample.json
# then restart ABNO DECK (or press "Refresh" in Settings after a restore)

5. Serial port permissions — never use sudo to run the app
Check what you have:
ls -l /dev/ttyUSB* /dev/ttyACM*
groups | grep dialout
Option A — dialout group (simplest):
sudo usermod -aG dialout "$USER"
# log out and back in, then plug the ESP32 in again
Option B — uaccess udev rule (no group, per-seat):
./install.sh --udev        # installs packaging/99-abno-deck.rules
The rule only sets TAG+="uaccess" so logind grants the logged-in user access. It never launches a GUI — starting a graphical app from a root udev rule is unsafe (wrong session, wrong environment, privilege escalation surface).
If opening the port still fails, the event log prints the exact diagnosis and fix (missing permission vs. port busy vs. device vanished), e.g.:
ERROR  permission denied for /dev/ttyUSB0
WARN   No permission for /dev/ttyUSB0. Fix it without sudo-ing the app:
WARN     ls -l /dev/ttyUSB0
WARN     sudo usermod -aG dialout "$USER"   (log out and back in)

6. Optional: auto-launch when the ESP32 is plugged in (opt-in)
./install.sh --auto-launch
This installs a systemd user path unit — the safe alternative to launching GUIs from udev:
~/.config/systemd/user/abno-deck-watch.path watches /dev/serial/by-id (which only exists while a USB serial adapter is present),
when it becomes non-empty it starts abno-deck-watch.service,
that service runs ~/.local/bin/abno-deck as your user, inside your login session — never as root.
Limitations, stated honestly:
It only works while you are logged in (a systemd --user session must run).
It triggers on the device node appearing, not on the ABNODECK:READY message; the app then performs the real handshake itself.
It assumes DISPLAY=:0 (fine on a normal single-seat MATE/X11 install).
If your system does not create /dev/serial/by-id (rare), it will not fire; start the app manually or from the menu.
Disable it:
systemctl --user disable --now abno-deck-watch.path
The app also always tries to reconnect on its own, so leaving it running works just as well if you prefer no auto-launch at all.

7. Button actions
Action	What it does	Needs
Launch application	Starts an executable + arguments (no shell)	the program installed
Open website	Hands an http(s):// URL to the default browser	gio or xdg-open
Keyboard shortcut	e.g. Ctrl+Alt+T via xdotool (X11) or wtype/ydotool (Wayland)	one of those tools
Media control	Play/Pause, next, previous, volume via MPRIS	playerctl (or dbus-send)
Custom command	Runs a command you wrote, with a warning, validation, optional shell opt-in and confirmation dialog	—
Do nothing	Idle key (still named/iconed)	—
Missing dependencies are reported with the exact install command — for example on Wayland, xdotool cannot inject keys and ABNO DECK tells you to install wtype instead of silently failing. Failures are always shown as failures in the event log and status bar.
The searchable application picker reads ~/.local/share/applications, /usr/local/share/applications and /usr/share/applications (freedesktop .desktop entries, field codes resolved, hidden entries skipped).

8. Configuration, profiles, backup
Everything lives under ~/.config/abno-deck/ (override with --config-dir or ABNO_DECK_CONFIG_DIR):
~/.config/abno-deck/
├── settings.json        # active profile, serial port, debounce, window size
├── profiles/
│   ├── default.json     # created automatically on first run
│   └── work.json        # one file per profile
├── backups/             # reserved for backups
└── abno-deck.log        # rotating application log
Profiles are validated on load. Corrupt files are never deleted: they are quarantined as <name>.corrupt-<timestamp> and a warning appears in the event log while a working default is rebuilt. Saves are atomic (temp file + rename), so a crash mid-save cannot corrupt your configuration.
Backup / restore — in Settings → Configuration backup, or from the CLI:
cd ~/.local/share/abno-deck/app
python3 -m src.backup create -o ~/abno-deck-backup.zip
python3 -m src.backup restore ~/abno-deck-backup.zip
Restoring validates every profile first and keeps a copy of the current configuration (abno-deck-pre-restore-<ts>/) before replacing anything.

9. Troubleshooting
Symptom	Fix
permission denied for /dev/ttyUSB0	§5 — dialout group or udev rule, then re-login
/dev/ttyUSB0 is busy	Close serial monitors / other instances
Stuck on CONNECTING	Check the cable/port: abno-deck --doctor; press the ESP32 reset button
A key pressed immediately after connecting does nothing	By design: the first ~0.5 s after the handshake discard reset/buffered noise. The log shows Ignored BUTTON:n ... startup window. Press the key again.
"no READY was received" warning	Port works, firmware doesn't send the handshake — check the firmware
Shortcut fails on Wayland	Install wtype (or ydotool + running ydotoold)
Media action: "no MPRIS player found"	Start a player, or sudo apt install playerctl
No emoji icons	Install a colour emoji font: sudo apt install fonts-noto-color-emoji
App won't start after install	abno-deck --doctor and tail -f ~/.config/abno-deck/abno-deck.log
Logs: ~/.config/abno-deck/abno-deck.log (DEBUG level, rotating).

10. Development
cd abno-deck
python3 -m unittest discover -s tests -t .   # 105+ tests, stdlib only
QT_QPA_PLATFORM=offscreen python3 tests/smoke_gui.py   # headless GUI smoke test
Layout:
main.py                     entry point (--doctor, --no-serial, --port, --profile)
src/
├── constants.py            protocol + app constants
├── protocol.py             strict serial message parser (pure, tested)
├── debounce.py             desktop-side debounce safeguard (pure)
├── ports.py                ESP32 serial port discovery
├── serial_io.py            SerialManager + background worker (Qt)
├── models.py               button/profile sanitising + validation (pure)
├── storage.py              atomic JSON writes, quarantine/recovery
├── profiles.py             ProfileStore: CRUD + settings + autosave
├── backup.py               ZIP backup/restore (+ CLI)
├── deps.py                 tool/session detection with install hints
├── desktop_entries.py      .desktop parsing for the app picker
├── actions/                validate() + execute() for all six action types
└── gui/                    theme, deck, editor, settings, main window
tests/                      protocol, debounce, models, profiles, backup,
                            ports, action execution, serial integration (pty)
packaging/                  .desktop template, udev rule, systemd user units
Architecture rules the code follows:
parsing/validation logic is Qt-free and unit tested,
the GUI thread never performs I/O: serial on a thread, actions on a pool,
every emitted signal carries the real outcome — success is only claimed when the underlying operation actually returned success.

11. Uninstall
cd abno-deck
./uninstall.sh            # keeps ~/.config/abno-deck
./uninstall.sh --purge    # also deletes profiles and settings
The script removes the app, launcher, menu entry, autostart entry, the user systemd units and the udev rule (it asks sudo only for the udev rule).

License
MIT — see LICENSE.
