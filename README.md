# ABNO DECK

### A DIY 4-KEY STREAM DECK FOR LINUX

**Made by ABNOX. Powered by ESP32. Built for Linux.**

> # ⚠️ OPEN SOURCE DOES NOT MEAN YOU CAN CHANGE MY NAME.
>
> # THIS PROJECT WAS MADE BY ABNOX.
>
> **YOU MAY FORK, MODIFY, AND REDISTRIBUTE THIS PROJECT UNDER THE TERMS OF THE MIT LICENSE. YOU MUST PRESERVE THE APPLICABLE COPYRIGHT AND LICENSE NOTICES. DO NOT REMOVE OR MISREPRESENT THE ORIGINAL AUTHORSHIP.**
>
> **MY NAME IS ABNOX. GIVE CREDIT WHERE CREDIT IS DUE.**

---

## WHAT IS ABNO DECK?

ABNO DECK is a homemade, four-button desktop controller that lets you control your Linux PC using physical buttons connected to an ESP32.

Press a button to launch an application, open a website, trigger a keyboard shortcut, control media playback, or run a custom command.

The project includes a Python desktop application with a dark cyberpunk/CRT interface, customizable buttons, JSON profiles, a live event log, and USB serial communication.

**Built on a budget. Designed for Linux. Made by ABNOX.**

## FEATURES

- **4 physical buttons** powered by an ESP32.
- **Customizable actions:** applications, websites, keyboard shortcuts, media controls, custom commands, and idle keys.
- **Dark CRT interface** with silver accents and a live event log.
- **Interactive desktop deck:** click on-screen buttons to test their actions.
- **JSON profiles:** create, rename, duplicate, delete, and switch between configurations.
- **USB serial communication** with automatic reconnection.
- **Input validation and debouncing** to reject malformed messages and reduce accidental repeated actions.
- **Configuration backup and restore.**
- **Linux desktop integration:** application launcher, menu entry, autostart, and optional device-triggered startup.
- **Security-conscious design:** serial messages identify buttons; they do not directly execute commands.
- **Automated tests** for protocol handling, profiles, storage, actions, and other components.

## HARDWARE

You need:

- An ESP32 development board.
- Four push buttons.
- Jumper wires.
- A USB cable capable of data transfer.
- A Linux computer.

### WIRING DIAGRAM

All four buttons share the same GND connection.

| ESP32 pin | Connect to |
|---|---|
| GPIO 18 | Button 1 |
| GPIO 19 | Button 2 |
| GPIO 21 | Button 3 |
| GPIO 22 | Button 4 |
| GND | One side of all four buttons |

Connect the other side of each button to its assigned GPIO pin.

The firmware uses `INPUT_PULLUP`, so external pull-up resistors are not required.

## HOW IT WORKS

```text
       FOUR PHYSICAL BUTTONS
                 |
                 v
              ESP32
                 |
          USB SERIAL / 115200
                 |
                 v
       ABNO DECK DESKTOP APP
                 |
       +---------+---------+
       |         |         |
    LAUNCH     SHORTCUT   MEDIA
       |         |         |
       v         v         v
    LINUX APPS  KEYBOARD  PLAYER
```

The ESP32 sends simple text messages over USB serial:

| Message | Meaning |
|---|---|
| `ABNODECK:READY` | Firmware startup handshake |
| `BUTTON:1` | Button 1 pressed |
| `BUTTON:2` | Button 2 pressed |
| `BUTTON:3` | Button 3 pressed |
| `BUTTON:4` | Button 4 pressed |

The desktop application validates incoming messages and maps accepted button IDs to locally configured actions.

## ESP32 FIRMWARE

Upload the ABNO DECK firmware to your ESP32 using the Arduino IDE or another compatible development environment.

The firmware uses GPIO pins 18, 19, 21, and 22 and sends serial messages at **115200 baud**.

Example firmware structure:

```cpp
const int buttons[] = {18, 19, 21, 22};
const int buttonCount = 4;

int lastReading[buttonCount] = {
    HIGH, HIGH, HIGH, HIGH
};

int stableState[buttonCount] = {
    HIGH, HIGH, HIGH, HIGH
};

unsigned long lastChange[buttonCount] = {
    0, 0, 0, 0
};

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

            if (stableState[i] == LOW) {
                Serial.print("BUTTON:");
                Serial.println(i + 1);
            }
        }
    }
}
```

If your repository contains the complete firmware as a separate file, use that file as the source of truth.

## INSTALLATION

**Designed for Debian 13 (Trixie), including the MATE desktop.**

Clone the repository:

```bash
git clone https://github.com/abnox43/abno-deck.git
cd abno-deck
```

Run the installer:

```bash
./install.sh --extras
```

The installer is designed to install the application for your user, set up its launcher and menu entry, and configure desktop autostart unless disabled.

Optional installer flags:

| Command | Purpose |
|---|---|
| `./install.sh --no-autostart` | Disable desktop-login autostart |
| `./install.sh --no-deps` | Skip dependency installation |
| `./install.sh --dialout` | Configure serial access using the `dialout` group |
| `./install.sh --udev` | Install the optional udev permission rule |
| `./install.sh --auto-launch` | Enable optional startup when the ESP32 is connected |

Review the installer before running it, especially when installing software from any source you have not personally verified.

## FIRST RUN

1. Connect the ESP32 to your computer using USB.
2. Launch ABNO DECK from your application menu or terminal.
3. Wait for the serial connection to establish.
4. Check the connection status and event log.
5. Press a physical button to test its assigned action.
6. Click a button's settings icon to customize its behavior.

The default profile provides example actions for launching a terminal, opening a browser, controlling media playback, and locking the screen. Availability depends on your desktop environment and installed applications.

## BUTTON ACTIONS

| Action | Description |
|---|---|
| Launch application | Start an executable with arguments |
| Open website | Open an HTTP or HTTPS URL in the default browser |
| Keyboard shortcut | Send a supported shortcut using the available input tool |
| Media control | Play, pause, skip tracks, or adjust volume where supported |
| Custom command | Execute a configured command subject to validation and safety settings |
| Do nothing | Keep a button available without triggering an action |

Keyboard injection differs between X11 and Wayland. Install the appropriate supported utility for your session.

## CONFIGURATION AND PROFILES

ABNO DECK stores user configuration under:

```text
~/.config/abno-deck/
├── settings.json
├── profiles/
├── backups/
└── abno-deck.log
```

Profiles use JSON files. The application validates profiles on load and is designed to recover from corrupted configuration files without silently deleting the original corrupted data.

Changes are saved automatically.

Configuration can be backed up and restored through the application's settings interface or supported command-line tools.

## SECURITY

**The ESP32 sends button identifiers, not shell commands.**

ABNO DECK validates incoming serial messages and rejects unsupported button IDs and malformed input.

Application launches use executable arguments rather than automatically interpreting received serial data as shell syntax. Custom commands have additional validation and safety controls.

Other protections include:

- Serial-side protocol validation.
- Desktop-side debouncing.
- Startup handling for buffered data and device resets.
- Background execution to keep the GUI responsive.
- User-level application execution instead of running the desktop application as root.
- Configuration validation and atomic saves.

No security mechanism should be considered infallible. Review the source code and use caution when configuring commands that can modify your system.

## TROUBLESHOOTING

| Problem | What to check |
|---|---|
| Serial permission denied | Configure `dialout` or the documented udev rule |
| Serial port busy | Close other serial monitors or application instances |
| Stuck on CONNECTING | Check the USB cable, port, and firmware handshake |
| First press is ignored | Check the startup safety window and event log |
| Keyboard shortcut fails | Check X11/Wayland compatibility and installed input tools |
| Media control fails | Check for a running media player and MPRIS support |
| Application fails to launch | Run `abno-deck --doctor` and inspect the application log |

Logs are stored at:

```text
~/.config/abno-deck/abno-deck.log
```

## DEVELOPMENT AND TESTING

Run the test suite from the repository root:

```bash
python3 -m unittest discover -s tests -t .
```

Run the GUI smoke test:

```bash
QT_QPA_PLATFORM=offscreen python3 tests/smoke_gui.py
```

The project separates protocol parsing, validation, configuration storage, action handling, serial communication, and GUI components to make testing and maintenance easier.

## UNINSTALL

Run:

```bash
./uninstall.sh
```

To also remove saved profiles and settings:

```bash
./uninstall.sh --purge
```

Review the effects before using the purge option.

## LICENSE

ABNO DECK is distributed under the **MIT License**. See [`LICENSE`](LICENSE) for the full terms.

The MIT License permits reuse, modification, and redistribution subject to its conditions, including preservation of applicable copyright and license notices.

**Open source means people can build on your work. It does not mean your authorship should be misrepresented.**

---

# MADE BY ABNOX.

**NOT MADE BY YOU. NOT CREATED BY SOME RANDOM ACCOUNT. MADE BY ABNOX.**

**IF YOU FORK IT, CREDIT THE ORIGINAL PROJECT.**

[GitHub Repository](https://github.com/abnox43/abno-deck)
