# bytello-cast

Cast your **whole Linux laptop screen** to a Bytello interactive panel over Wi-Fi.
Bytello only ships Windows/iOS apps, but the panel's receiver speaks Google Cast
(it advertises as `_googlecast._tcp`, e.g. `BytelloShare1234`) and accepts real
Chrome Cast Streaming. This project drives a dedicated Brave/Chromium instance
through the DevTools `Cast` domain, so no reverse engineering of the panel is needed.

- `bytello-cast-gui` - **main app**: window with panel picker, whole-screen/tab mode, Start/Stop, live status + log, auto-reconnect, minimise to tray
- `bytello-cast-tray` - minimal tray-only version: click to cast the screen, click to stop (grey = idle, yellow = connecting, green = casting)
- `bytello-cast` - CLI: `--desktop` (whole screen), default tab mirroring, `--list`, `--quit-browser`
- `bytello-cast-toggle` - one-shot start/stop script, handy for a keyboard shortcut

## Requirements
Linux with systemd user session, Brave (`brave-browser`) or a Chromium that exposes the `Cast`
DevTools domain, Python 3 with PyQt6 (tray) and `aiohttp`. Tested on Kali, KDE Plasma (Wayland).
The laptop and panel must be on the same network (mDNS must work).

## Install
```
./install.sh            # add --autostart to start the tray at login
```

## Notes
- Cold start takes ~15-20 s (Brave starts, then Cast discovery must settle); with "Keep helper browser running" it is faster.
  Starting mirroring too early crashes Brave, hence `--settle` (default 12 s).
- The helper browser uses its own profile in `~/.config/bytello-cast/brave`.
- Video only; audio is not sent in this version.
- Not affiliated with Bytello or Google.

## License
MIT
