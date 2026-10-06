#!/bin/bash
# Installs fi-osk for the current user only (no root needed except for the dependency).
set -euo pipefail
cd "$(dirname "$0")"

if ! rpm -q gtk4-layer-shell >/dev/null 2>&1; then
    echo "Installing dependency gtk4-layer-shell (needs your password)…"
    sudo dnf install -y gtk4-layer-shell
fi

install -Dm755 fi-osk.py "$HOME/.local/bin/fi-osk"
install -Dm644 fi-osk.desktop "$HOME/.local/share/applications/io.github.fiosk.Keyboard.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Installed. Start it from the app menu: 'On-Screen Keyboard (Finnish)'."
echo "Tip: right-click it in the menu → 'Pin to Task Manager' for one-click open/close."
