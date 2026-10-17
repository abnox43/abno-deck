"""Action runner: validation + honest execution of the six action types.

Design rules enforced here:

* ``validate(action)`` is pure (no subprocess, no I/O) and is used by the
  editor dialog before a button can be saved.
* ``execute(action)`` returns a :class:`ActionResult` describing exactly what
  happened.  Failures are reported as failures - never dressed up as success.
* Subprocesses use argument lists whenever possible; ``shell=True`` is only
  reachable through the explicit ``command`` action with ``use_shell`` set by
  the user.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass, field

from ..deps import media_backend, session_type, shortcut_backend, uri_backend, which
from ..models import validate_action


@dataclass
class ActionResult:
    ok: bool
    summary: str
    detail: str = ""
    backend: str = ""
    warnings: list[str] = field(default_factory=list)

    def log_line(self) -> str:
        text = self.summary
        if self.detail:
            text = f"{text} — {self.detail}"
        return text


def validate(action: dict) -> list[str]:
    """Static validation (shared with the button editor)."""
    return validate_action(action)


def describe(action: dict) -> str:
    from ..models import describe_action

    return describe_action(action)


def execute(action: dict) -> ActionResult:
    """Dispatch an action dict; never raises."""
    if not isinstance(action, dict):
        return ActionResult(False, "Invalid action", "action configuration is not an object")
    action_type = action.get("type", "none")
    runner = _RUNNERS.get(action_type, _run_unknown)
    try:
        return runner(action)
    except Exception as exc:  # defensive: a runner bug must not kill the GUI
        return ActionResult(False, f"{action_type} failed", f"unexpected error: {exc}")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _run_command(argv: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        text=True,
        errors="replace",
    )


def _stderr_text(process: subprocess.CompletedProcess, limit: int = 200) -> str:
    text = (process.stderr or "").strip().replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


# --------------------------------------------------------------------------
# runners
# --------------------------------------------------------------------------
def _run_unknown(action: dict) -> ActionResult:
    return ActionResult(False, "Unknown action type",
                        f"{action.get('type')!r} is not supported")


def _run_none(action: dict) -> ActionResult:
    return ActionResult(True, "No action configured",
                        "this button intentionally does nothing")


def _run_launch_app(action: dict) -> ActionResult:
    from ..models import validate_action

    problems = validate_action({"type": "launch_app", **action})
    if problems:
        return ActionResult(False, "Launch failed", "; ".join(problems))

    executable = action["executable"].strip()
    arguments_text = (action.get("arguments") or "").strip()

    argv = [executable]
    if arguments_text:
        try:
            argv.extend(shlex.split(arguments_text))
        except ValueError as exc:
            return ActionResult(False, "Launch failed", f"bad arguments: {exc}")

    # Resolve the program without a shell.
    if "/" in executable:
        import os

        if not os.path.isfile(executable):
            return ActionResult(False, "Launch failed",
                                f"{executable} does not exist")
        if not os.access(executable, os.X_OK):
            return ActionResult(False, "Launch failed",
                                f"{executable} is not executable")
    else:
        resolved = which(executable)
        if not resolved:
            return ActionResult(False, "Launch failed",
                                f"'{executable}' was not found in PATH "
                                "(install the program or use its full path)")
        argv[0] = resolved

    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        return ActionResult(False, "Launch failed", str(exc))
    return ActionResult(True, f"Launched {executable}", backend=argv[0])


def _run_open_url(action: dict) -> ActionResult:
    from ..models import validate_action

    problems = validate_action({"type": "open_url", **action})
    if problems:
        return ActionResult(False, "Open URL failed", "; ".join(problems))

    url = action["url"].strip()
    backend = uri_backend()
    if backend is None:
        return ActionResult(
            False, "Open URL failed",
            "no URL handler available (install xdg-utils or libglib2.0-bin)",
        )

    if backend.key == "gio":
        argv = [backend.path, "open", url]
    else:
        argv = [backend.path, url]
    process = _run_command(argv, timeout=20)
    if process.returncode == 0:
        return ActionResult(True, f"Opened {url}", backend=backend.label)
    detail = _stderr_text(process) or f"{backend.label} exited with code {process.returncode}"
    return ActionResult(False, f"Open URL failed ({url})", detail, backend=backend.label)


def _run_shortcut(action: dict) -> ActionResult:
    from ..models import parse_shortcut

    if parse_shortcut(action.get("keys", "")) is None:
        return ActionResult(False, "Shortcut failed", "no valid shortcut configured")

    backend = shortcut_backend()
    if backend is None:
        return ActionResult(
            False, "Shortcut failed",
            "no keyboard injection tool found. X11: sudo apt install xdotool · "
            "Wayland: sudo apt install wtype (or ydotool + ydotoold)",
        )

    if backend.key == "xdotool":
        return _shortcut_xdotool(backend, action["keys"])
    if backend.key == "wtype":
        return _shortcut_wtype(backend, action["keys"])
    if backend.key == "ydotool":
        return _shortcut_ydotool(backend, action["keys"])
    return ActionResult(False, "Shortcut failed", f"unsupported backend {backend.key}")


def _shortcut_xdotool(backend, keys: str) -> ActionResult:
    combo = keys.replace(" ", "").lower()
    process = _run_command([backend.path, "key", "--clearmodifiers", combo], timeout=10)
    if process.returncode == 0:
        return ActionResult(True, f"Sent shortcut {keys}", backend="xdotool")
    detail = _stderr_text(process) or f"xdotool exited with code {process.returncode}"
    if session_type() == "wayland":
        detail += " (Wayland session: xdotool cannot inject keys — install wtype)"
    return ActionResult(False, f"Shortcut {keys} failed", detail, backend="xdotool")


def _shortcut_wtype(backend, keys: str) -> ActionResult:
    from ..models import parse_shortcut

    modifiers, key = parse_shortcut(keys)  # type: ignore[misc]
    argv = [backend.path]
    for modifier in modifiers:
        argv += ["-M", modifier]
    argv += ["-k", key]
    for modifier in reversed(modifiers):
        argv += ["-m", modifier]
    process = _run_command(argv, timeout=10)
    if process.returncode == 0:
        return ActionResult(True, f"Sent shortcut {keys}", backend="wtype")
    detail = _stderr_text(process) or f"wtype exited with code {process.returncode}"
    return ActionResult(False, f"Shortcut {keys} failed", detail, backend="wtype")


_YOLOTOOL_KEYS = {
    "esc": 1, "1": 2, "2": 3, "3": 4, "4": 5, "5": 6, "6": 7, "7": 8, "8": 9, "9": 10,
    "0": 11, "minus": 12, "equal": 13, "backspace": 14, "tab": 15,
    "q": 16, "w": 17, "e": 18, "r": 19, "t": 20, "y": 21, "u": 22, "i": 23, "o": 24,
    "p": 25, "bracketleft": 26, "bracketright": 27, "return": 28, "enter": 28,
    "ctrl": 29, "control": 29, "a": 30, "s": 31, "d": 32, "f": 33, "g": 34, "h": 35,
    "j": 36, "k": 37, "l": 38, "semicolon": 39, "apostrophe": 40, "grave": 41,
    "shift": 42, "backslash": 43, "z": 44, "x": 45, "c": 46, "v": 47, "b": 48,
    "n": 49, "m": 50, "comma": 51, "period": 52, "slash": 53, "alt": 56, "space": 57,
    "capslock": 58, "f1": 59, "f2": 60, "f3": 61, "f4": 62, "f5": 63, "f6": 64,
    "f7": 65, "f8": 66, "f9": 67, "f10": 68, "numlock": 69, "scrolllock": 70,
    "f11": 87, "f12": 88, "super": 125, "meta": 125,
    "left": 105, "right": 106, "up": 103, "down": 108, "home": 102, "end": 107,
    "pageup": 104, "pagedown": 109, "insert": 110, "delete": 111,
}


def _shortcut_ydotool(backend, keys: str) -> ActionResult:
    from ..models import parse_shortcut

    modifiers, key = parse_shortcut(keys)  # type: ignore[misc]
    sequence: list[int] = []
    for modifier in modifiers:
        code = _YOLOTOOL_KEYS.get(modifier)
        if code is None:
            return ActionResult(False, f"Shortcut {keys} failed",
                                f"ydotool backend cannot send modifier '{modifier}'")
        sequence.append(code)
    key_code = _YOLOTOOL_KEYS.get(key) or _YOLOTOOL_KEYS.get(key.lower())
    if key_code is None and key.lower().startswith("f") and key[1:].isdigit():
        key_code = _YOLOTOOL_KEYS.get(f"f{int(key[1:])}")
    if key_code is None:
        return ActionResult(False, f"Shortcut {keys} failed",
                            f"ydotool backend cannot map key '{key}'")
    sequence.append(key_code)

    args: list[str] = []
    for code in sequence:
        args.append(f"{code}:1")
    for code in reversed(sequence):
        args.append(f"{code}:0")
    process = _run_command([backend.path, "key", *args], timeout=10)
    if process.returncode == 0:
        return ActionResult(True, f"Sent shortcut {keys}", backend="ydotool")
    detail = _stderr_text(process) or f"ydotool exited with code {process.returncode}"
    if "ydotoold" in detail.lower() or "permission" in detail.lower():
        detail += " — is the ydotoold daemon running?"
    return ActionResult(False, f"Shortcut {keys} failed", detail, backend="ydotool")


def _run_media(action: dict) -> ActionResult:
    command = str(action.get("command", "")).strip().lower()
    from ..models import MEDIA_COMMANDS, MEDIA_LABELS

    if command not in MEDIA_COMMANDS:
        return ActionResult(False, "Media failed", f"unknown media command {command!r}")

    backend = media_backend()
    if backend is None:
        return ActionResult(
            False, "Media failed",
            "no media control backend found. Install one with: sudo apt install playerctl",
        )
    if backend.key == "playerctl":
        return _media_playerctl(backend, command)
    return _media_mpris(backend, command)


def _media_playerctl(backend, command: str) -> ActionResult:
    from ..models import MEDIA_LABELS

    label = MEDIA_LABELS.get(command, command)
    if command in ("volume_up", "volume_down"):
        read = _run_command([backend.path, "volume"], timeout=10)
        if read.returncode != 0:
            detail = _stderr_text(read) or "no player answered"
            return ActionResult(False, f"{label} failed", detail, backend="playerctl")
        try:
            current = float((read.stdout or "0").strip())
        except ValueError:
            return ActionResult(False, f"{label} failed",
                                f"could not read volume: {(read.stdout or '').strip()!r}",
                                backend="playerctl")
        step = 0.1
        target = max(0.0, min(1.0, current + (step if command == "volume_up" else -step)))
        write = _run_command([backend.path, "volume", f"{target:.2f}"], timeout=10)
        if write.returncode != 0:
            detail = _stderr_text(write) or f"playerctl exited with code {write.returncode}"
            return ActionResult(False, f"{label} failed", detail, backend="playerctl")
        return ActionResult(True, f"{label}: volume {current:.0%} → {target:.0%}",
                            backend="playerctl")

    process = _run_command([backend.path, command], timeout=10)
    if process.returncode == 0:
        return ActionResult(True, f"Media: {label}", backend="playerctl")
    detail = _stderr_text(process) or f"playerctl exited with code {process.returncode}"
    return ActionResult(False, f"Media {label} failed", detail, backend="playerctl")


_MPRIS_DEST = "org.mpris.MediaPlayer2"
_MPRIS_PATH = "/org/mpris/MediaPlayer2"
_MPRIS_PLAYER = "org.mpris.MediaPlayer2.Player"


def _mpris_players(dbus_send: str) -> list[str]:
    try:
        process = _run_command(
            [dbus_send, "--print-reply", "--dest=org.freedesktop.DBus",
             "/org/freedesktop/DBus", "org.freedesktop.DBus.ListNames"],
            timeout=10,
        )
    except Exception:
        return []
    players: list[str] = []
    for line in (process.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("string ") and _MPRIS_DEST in line:
            name = line[len("string "):].strip().strip('"')
            if name.startswith(_MPRIS_DEST):
                players.append(name)
    return players


def _media_mpris(backend, command: str) -> ActionResult:
    from ..models import MEDIA_LABELS

    label = MEDIA_LABELS.get(command, command)
    players = _mpris_players(backend.path)
    if not players:
        return ActionResult(
            False, f"Media {label} failed",
            "no MPRIS player found on the session bus (start a music/video player)",
            backend="dbus-send",
        )
    dest = players[0]
    short = dest.replace(_MPRIS_DEST + ".", "")

    if command in ("play_pause", "next", "previous"):
        method = {"play_pause": "PlayPause", "next": "Next", "previous": "Previous"}[command]
        process = _run_command(
            [backend.path, "--print-reply", f"--dest={dest}", _MPRIS_PATH,
             f"{_MPRIS_PLAYER}.{method}"],
            timeout=10,
        )
        if process.returncode == 0:
            return ActionResult(True, f"Media: {label} ({short})", backend="dbus-send")
        detail = _stderr_text(process) or f"dbus-send exited with code {process.returncode}"
        return ActionResult(False, f"Media {label} failed", detail, backend="dbus-send")

    # volume up/down: read the Volume property, compute, write it back
    read = _run_command(
        [backend.path, "--print-reply", f"--dest={dest}", _MPRIS_PATH,
         "org.freedesktop.DBus.Properties.Get",
         f"string:{_MPRIS_PLAYER}", "string:Volume"],
        timeout=10,
    )
    if read.returncode != 0:
        detail = _stderr_text(read) or "player does not expose the Volume property"
        return ActionResult(False, f"{label} failed", detail, backend="dbus-send")
    import re

    match = re.search(r"double\s+([0-9.]+)", read.stdout or "")
    if not match:
        return ActionResult(False, f"{label} failed",
                            "could not parse the player volume", backend="dbus-send")
    current = float(match.group(1))
    step = 0.1
    target = max(0.0, min(1.0, current + (step if command == "volume_up" else -step)))
    write = _run_command(
        [backend.path, "--print-reply", f"--dest={dest}", _MPRIS_PATH,
         "org.freedesktop.DBus.Properties.Set",
         f"string:{_MPRIS_PLAYER}", "string:Volume", f"variant:double:{target:.3f}"],
        timeout=10,
    )
    if write.returncode == 0:
        return ActionResult(True, f"{label}: volume {current:.0%} → {target:.0%} ({short})",
                            backend="dbus-send")
    detail = _stderr_text(write) or f"dbus-send exited with code {write.returncode}"
    return ActionResult(False, f"{label} failed", detail, backend="dbus-send")


def _run_command_action(action: dict) -> ActionResult:
    from ..models import validate_action

    problems = validate_action({"type": "command", **action})
    if problems:
        return ActionResult(False, "Command refused", "; ".join(problems))

    line = action["command"].strip()
    use_shell = bool(action.get("use_shell"))
    warnings: list[str] = []
    if use_shell:
        warnings.append("executed through the shell because the user allowed it")

    try:
        if use_shell:
            process = subprocess.run(
                line,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
                check=False,
                text=True,
                errors="replace",
            )
        else:
            argv = shlex.split(line)
            if not argv:
                return ActionResult(False, "Command refused", "empty command line")
            if not (os_path_exists(argv[0]) if "/" in argv[0] else which(argv[0])):
                return ActionResult(
                    False, "Command refused",
                    f"'{argv[0]}' was not found — fix the command before saving it",
                )
            process = _run_command(argv, timeout=60)
    except subprocess.TimeoutExpired:
        return ActionResult(False, "Command failed", "timed out after 60 s", warnings=warnings)
    except ValueError as exc:
        return ActionResult(False, "Command refused", f"bad quoting: {exc}", warnings=warnings)
    except OSError as exc:
        return ActionResult(False, "Command failed", str(exc), warnings=warnings)

    if process.returncode == 0:
        detail = (process.stdout or "").strip().replace("\n", " ")[:200]
        return ActionResult(True, "Command finished", detail, warnings=warnings)
    detail = _stderr_text(process) or f"exit code {process.returncode}"
    return ActionResult(False, f"Command failed (exit {process.returncode})", detail,
                        warnings=warnings)


def os_path_exists(path: str) -> bool:
    import os

    return os.path.exists(path)


_RUNNERS = {
    "launch_app": _run_launch_app,
    "open_url": _run_open_url,
    "shortcut": _run_shortcut,
    "media": _run_media,
    "command": _run_command_action,
    "none": _run_none,
}

__all__ = ["ActionResult", "describe", "execute", "validate"]
