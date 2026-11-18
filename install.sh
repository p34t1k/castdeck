#!/bin/sh
# Installs bytello-cast for the current user: venv, launchers, app-menu entry.
# Pass --autostart to also start the tray app at login.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
python3 -m venv --system-site-packages "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
for f in bytello-cast bytello-cast-toggle bytello-cast-tray; do ln -sf "$HERE/$f" "$HOME/.local/bin/$f"; done
cat > "$HOME/.local/share/applications/bytello-cast.desktop" <<D
[Desktop Entry]
Type=Application
Name=Bytello Cast
Comment=Cast the whole laptop screen to a Bytello panel
Exec=$HERE/bytello-cast-tray
Icon=video-display
Terminal=false
Categories=Utility;AudioVideo;
D
if [ "$1" = "--autostart" ]; then
  mkdir -p "$HOME/.config/autostart"
  cp "$HOME/.local/share/applications/bytello-cast.desktop" "$HOME/.config/autostart/"
fi
echo "Installed. Launch 'Bytello Cast' from the app menu, or run: bytello-cast-tray"
