#!/bin/sh
# Installs castdeck for the current user: venv, launchers, app-menu entry.
# Pass --autostart to also start the tray app at login.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 -m venv --system-site-packages "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
for f in castdeck castdeck-toggle castdeck-tray castdeck-gui; do ln -sf "$HERE/$f" "$HOME/.local/bin/$f"; done
cat > "$HOME/.local/share/applications/castdeck.desktop" <<D
[Desktop Entry]
Type=Application
Name=Castdeck
Comment=Cast your Linux screen to TVs, panels and Chromecast devices
Exec=$HERE/castdeck-gui
Icon=video-display
Terminal=false
Categories=Utility;AudioVideo;
D
if [ "$1" = "--autostart" ]; then
  mkdir -p "$HOME/.config/autostart"
  cp "$HOME/.local/share/applications/castdeck.desktop" "$HOME/.config/autostart/"
fi
echo "Installed. Launch 'Castdeck' from the app menu, or run: castdeck-gui"
