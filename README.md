# Castdeck

Cast your **whole Linux screen, with desktop audio,** to any **Google Cast** receiver on your network:
Chromecast, Google TV, Android TV, smart TVs and interactive classroom panels
(developed against a Bytello ScreenSharePro panel). Standalone: **no browser needed.**

Castdeck captures the screen through the desktop portal (PipeWire), encodes H.264 + Opus with
GStreamer, and speaks the Cast Streaming protocol itself (written from Google's open-source
`openscreen` specification). It reconnects automatically if the receiver drops.

- `castdeck-gui` - **main app**: receiver picker, Start/Stop, live status + log, auto-reconnect, tray
- `castdeck-tray` - tray-only version: click to cast, click to stop (grey = idle, yellow = connecting, green = casting)
- `castdeck` - CLI: `--list`, `--name`, `--host`, `--fps`, `--bitrate`, `--no-audio`, `--reset`
- `castdeck-toggle` - one-shot start/stop script, handy for a keyboard shortcut
- `castdeck-brave` - legacy backend that drives a Brave/Chromium Cast engine instead (kept as a fallback)

## Requirements
Linux (Wayland/KDE tested) with systemd user session, `xdg-desktop-portal` + PipeWire, Avahi (`avahi-browse`),
`pactl`, Python 3 with `python3-gi`, `python3-dbus`, `python3-cryptography`, PyQt6 (GUI/tray), and GStreamer
plugins: `pipewire`, `x264` (plugins-ugly), `opus`, `pulseaudio`, `videoconvert`, `videoscale`.
Computer and receiver must be on the same network (mDNS must work).

## Install
```
./install.sh            # add --autostart to start the tray at login
```

## Usage
```
castdeck --list                          # receivers found on the network
castdeck --name "Living Room"            # cast the whole screen (name is a substring; omit for the first receiver)
castdeck --host 192.168.1.45             # skip discovery
castdeck --reset                         # forget the saved screen choice (shows the picker again)
```
The first cast shows a screen-share picker; your choice is remembered, so reconnects need no clicks.

## Notes
- Audio is the desktop's default output (its monitor source).
- Receivers must support Chrome Mirroring (app 0F5096E8): standard Chromecasts and Bytello panels do. Others are untested.
- Tested on one receiver and one Linux setup so far. Issues and reports are welcome.
- Not affiliated with Google or Bytello.

## License
MIT
