#!/usr/bin/env bash
# ABNO DECK - uninstaller.
#
# Removes everything install.sh created. Your configuration in
# ~/.config/abno-deck is kept unless you pass --purge.
#
# Usage:
#   ./uninstall.sh           # remove app, launcher, desktop entries, units, udev rule
#   ./uninstall.sh --purge   # additionally delete ~/.config/abno-deck (profiles!)
set -euo pipefail

APP_ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/abno-deck"
TARGET="$APP_ROOT/app"
WRAPPER="$HOME/.local/bin/abno-deck"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/abno-deck.desktop"
AUTOSTART_FILE="$HOME/.config/autostart/abno-deck.desktop"
ICON_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/abno-deck.svg"
USER_UNIT_DIR="$HOME/.config/systemd/user"
UDEV_RULE_DST="/etc/udev/rules.d/99-abno-deck.rules"
CONFIG_DIR="${ABNO_DECK_CONFIG_DIR:-$HOME/.config/abno-deck}"

PURGE=0
for arg in "$@"; do
  case "$arg" in
    --purge) PURGE=1 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 1 ;;
  esac
done

log() { printf '\033[1;36m[abno-deck]\033[0m %s\n' "$*"; }

# stop the optional auto-launch unit first
if command -v systemctl >/dev/null 2>&1; then
  systemctl --user disable --now abno-deck-watch.path >/dev/null 2>&1 || true
fi
rm -f "$USER_UNIT_DIR/abno-deck-watch.path" "$USER_UNIT_DIR/abno-deck-watch.service"
command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload >/dev/null 2>&1 || true

rm -f "$DESKTOP_FILE" "$AUTOSTART_FILE" "$ICON_FILE" "$WRAPPER"
rm -rf "$APP_ROOT"
command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$(dirname "$DESKTOP_FILE")" >/dev/null 2>&1 || true

# udev rule needs root to remove; only touch it when it is ours
if [ -f "$UDEV_RULE_DST" ]; then
  if [ "$(id -u)" -eq 0 ]; then
    rm -f "$UDEV_RULE_DST"
    udevadm control --reload-rules 2>/dev/null || true
    log "removed $UDEV_RULE_DST"
  elif command -v sudo >/dev/null 2>&1; then
    if sudo rm -f "$UDEV_RULE_DST"; then
      sudo udevadm control --reload-rules 2>/dev/null || true
      log "removed $UDEV_RULE_DST"
    fi
  else
    echo "note: could not remove $UDEV_RULE_DST (needs root)" >&2
  fi
fi

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$CONFIG_DIR"
  log "removed configuration directory $CONFIG_DIR"
else
  if [ -d "$CONFIG_DIR" ]; then
    log "kept configuration in $CONFIG_DIR (use --purge to delete it)"
  fi
fi

log "ABNO DECK uninstalled"
