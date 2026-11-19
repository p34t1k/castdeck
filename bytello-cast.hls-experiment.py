#!/usr/bin/env python3
"""bytello-cast: mirror this Linux (Wayland/KDE) screen to a Bytello panel
(Google Cast receiver) over Wi-Fi.  Capture: xdg-desktop-portal ScreenCast ->
PipeWire; encode: GStreamer H.264 -> live HLS; cast: pychromecast."""
import argparse, os, shutil, signal, socket, sys, tempfile, threading, time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import dbus, dbus.mainloop.glib
import gi
gi.require_version("Gst", "1.0")
from gi.repository import GLib, Gst
import pychromecast

CFG = os.path.expanduser("~/.config/bytello-cast")
TOKEN_FILE = os.path.join(CFG, "restore_token")
DEFAULT_NAME = "BytelloShare"

def my_ip(target):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((target, 8009)); ip = s.getsockname()[0]; s.close(); return ip

def find_panel(name, host):
    if host:
        return host, 8009
    import zeroconf
    chromecasts, browser = pychromecast.discovery.discover_chromecasts(timeout=6)
    pychromecast.discovery.stop_discovery(browser)
    for c in chromecasts:
        if name.lower() in (c.friendly_name or "").lower():
            return c.host, c.port
    sys.exit(f"No Cast device matching '{name}' found. Use --host IP.")

# ---- portal screencast -------------------------------------------------
def portal_screencast():
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
    sc = dbus.Interface(portal, "org.freedesktop.portal.ScreenCast")
    sender = bus.get_unique_name()[1:].replace(".", "_")
    loop = GLib.MainLoop(); n = [0]
    def request(method, *args, opts):
        n[0] += 1; tok = f"bc{os.getpid()}_{n[0]}"
        opts["handle_token"] = tok
        path = f"/org/freedesktop/portal/desktop/request/{sender}/{tok}"
        res = {}
        def cb(code, results): res["c"], res["r"] = code, results; loop.quit()
        bus.add_signal_receiver(cb, "Response", "org.freedesktop.portal.Request", path=path)
        method(*args, opts)
        loop.run()
        if res["c"] != 0: sys.exit("Screen share was cancelled/denied.")
        return res["r"]
    r = request(sc.CreateSession, opts={"session_handle_token": f"bcs{os.getpid()}"})
    session = r["session_handle"]
    token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else None
    o = {"types": dbus.UInt32(1), "multiple": False, "cursor_mode": dbus.UInt32(2),
         "persist_mode": dbus.UInt32(2)}
    if token: o["restore_token"] = token
    request(sc.SelectSources, session, opts=o)
    r = request(sc.Start, session, "", opts={})
    if "restore_token" in r:
        os.makedirs(CFG, exist_ok=True); open(TOKEN_FILE, "w").write(str(r["restore_token"]))
    node = int(r["streams"][0][0])
    fd = sc.OpenPipeWireRemote(session, {}).take()
    return node, fd

# ---- HTTP (HLS) server --------------------------------------------------
class H(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()
    def log_message(self, *a): pass

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--name", default=DEFAULT_NAME, help="panel friendly-name substring")
    ap.add_argument("--host", help="panel IP (skip discovery)")
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--bitrate", type=int, default=6000, help="kbit/s")
    ap.add_argument("--audio", action="store_true", help="also send desktop audio")
    ap.add_argument("--reset", action="store_true", help="forget saved screen choice")
    a = ap.parse_args()
    if a.reset and os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
    w, h = a.res.split("x")

    host, port = find_panel(a.name, a.host)
    print(f"Panel: {host}:{port}")
    node, fd = portal_screencast()
    print(f"Screen node {node}")

    d = tempfile.mkdtemp(prefix="bytello-cast-")
    srv = ThreadingHTTPServer(("0.0.0.0", 0), partial(H, directory=d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://{my_ip(host)}:{srv.server_port}/live.m3u8"

    Gst.init(None)
    audio = ""
    if a.audio:
        audio = ('pulsesrc device=@DEFAULT_MONITOR@ ! audioconvert ! audioresample ! '
                 'avenc_aac bitrate=128000 ! aacparse ! queue ! mux.')
    pipe = Gst.parse_launch(
        f'pipewiresrc fd={fd} path={node} always-copy=true do-timestamp=true ! queue '
        f'! videoconvert ! videoscale add-borders=true ! videorate '
        f'! video/x-raw,width={w},height={h},framerate={a.fps}/1,pixel-aspect-ratio=1/1 '
        f'! x264enc tune=zerolatency speed-preset=veryfast bitrate={a.bitrate} '
        f'key-int-max={a.fps} bframes=0 ! video/x-h264,profile=main ! h264parse ! queue '
        f'! mux.  hlssink2 name=mux target-duration=1 max-files=8 playlist-length=4 '
        f'location={d}/seg%05d.ts playlist-location={d}/live.m3u8 '
        f'playlist-root=http://{my_ip(host)}:{srv.server_port} {audio}')
    pipe.set_state(Gst.State.PLAYING)
    for _ in range(40):
        if os.path.exists(f"{d}/live.m3u8"): break
        time.sleep(0.25)
    else:
        pipe.set_state(Gst.State.NULL); sys.exit("Encoder produced no stream.")

    cast = pychromecast.get_chromecast_from_host((host, port, None, None, "Panel"))
    cast.wait(timeout=15)
    mc = cast.media_controller
    mc.play_media(url, "application/x-mpegURL", stream_type="LIVE")
    mc.block_until_active(timeout=20)
    print(f"Casting {url}\nCtrl+C to stop.")

    def stop(*_):
        try: mc.stop(); cast.quit_app()
        except Exception: pass
        pipe.set_state(Gst.State.NULL); srv.shutdown(); shutil.rmtree(d, True); os._exit(0)
    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    bus = pipe.get_bus()
    while True:
        m = bus.timed_pop_filtered(500*Gst.MSECOND, Gst.MessageType.ERROR | Gst.MessageType.EOS)
        if m: print("GStreamer:", m.parse_error()[0] if m.type == Gst.MessageType.ERROR else "EOS"); stop()

if __name__ == "__main__":
    main()
