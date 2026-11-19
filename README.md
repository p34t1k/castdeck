# Castdeck

Cast your **whole Linux screen** (or a single tab) to any **Google Cast** receiver on your network:
Chromecast, Google TV, Android TV, Nest displays, smart TVs and interactive classroom panels
(tested with a Bytello ScreenSharePro panel). It works on Wayland and X11, and needs no
reverse engineering: Castdeck drives a dedicated Brave/Chromium instance through the DevTools
`Cast` domain and supervises it, restarting and resuming the cast if it drops.

- `castdeck-gui` - **main app**: window with receiver picker, whole-screen/tab mode, Start/Stop, live status + log, auto-reconnect, minimise to tray
- `castdeck-tray` - tray-only version: click to cast, click to stop (grey = idle, yellow = connecting, green = casting)
- `castdeck` - CLI: `--desktop` (whole screen), default tab mirroring, `--list`, `--name`, `--quit-browser`
- `castdeck-toggle` - one-shot start/stop script, handy for a keyboard shortcut

## Requirements
Linux with a systemd user session, Brave (`brave-browser`) or a Chromium that exposes the `Cast`
DevTools domain, Python 3 with PyQt6 (GUI/tray) and `aiohttp`. Tested on Kali, KDE Plasma (Wayland).
The computer and receiver must be on the same network (mDNS must work).

## Install
```
./install.sh            # add --autostart to start the tray at login
```

## Usage
```
castdeck --list                          # show receivers found on the network
castdeck --desktop --name "Living Room"  # cast the whole screen (name is a substring match; omit to use the first receiver)
castdeck --quit-browser                  # stop the helper browser
```

## Notes
- Cold start takes ~15-20 s (the browser starts, then Cast discovery must settle); with "Keep helper browser running" it is faster.
  Starting mirroring too early crashes the browser, hence `--settle` (default 12 s).
- On Wayland, a screen-share picker appears the first time; choose the screen and share.
- The helper browser uses its own profile in `~/.config/castdeck/brave`.
- Audio: **tab mode carries the tab's audio**. **Whole-screen mode is video only**, because Chrome on Linux has no system-audio capture for desktop mirroring.
- Verified over a full 4-hour session with no drops on a Bytello panel.
- Not affiliated with Google or Bytello.

## License
MIT
