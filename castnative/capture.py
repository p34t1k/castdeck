"""Wayland/X11 screen capture via xdg-desktop-portal ScreenCast -> PipeWire.
Persists the user's screen choice (restore_token) so reconnects need no picker."""
import os, sys
import dbus, dbus.mainloop.glib
from gi.repository import GLib

CFG = os.path.expanduser("~/.config/castdeck")
TOKEN_FILE = os.path.join(CFG, "restore_token")


def forget():
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)


class Portal:
    """Holds the portal session open; keep this object alive while capturing."""

    def open(self, cursor=True):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = self.bus = dbus.SessionBus()
        portal = bus.get_object("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop")
        sc = self.sc = dbus.Interface(portal, "org.freedesktop.portal.ScreenCast")
        sender = bus.get_unique_name()[1:].replace(".", "_")
        loop, n = GLib.MainLoop(), [0]

        def request(method, *args, opts):
            n[0] += 1
            tok = f"cd{os.getpid()}_{n[0]}"
            opts["handle_token"] = tok
            path = f"/org/freedesktop/portal/desktop/request/{sender}/{tok}"
            res = {}

            def cb(code, results):
                res["c"], res["r"] = code, results
                loop.quit()
            bus.add_signal_receiver(cb, "Response", "org.freedesktop.portal.Request", path=path)
            method(*args, opts)
            loop.run()
            if res["c"] != 0:
                raise RuntimeError("screen share cancelled or denied")
            return res["r"]

        r = request(sc.CreateSession, opts={"session_handle_token": f"cds{os.getpid()}"})
        self.session = r["session_handle"]
        token = open(TOKEN_FILE).read().strip() if os.path.exists(TOKEN_FILE) else None
        o = {"types": dbus.UInt32(1), "multiple": False,
             "cursor_mode": dbus.UInt32(2 if cursor else 1), "persist_mode": dbus.UInt32(2)}
        if token:
            o["restore_token"] = token
        request(sc.SelectSources, self.session, opts=o)
        r = request(sc.Start, self.session, "", opts={})
        if "restore_token" in r:
            os.makedirs(CFG, exist_ok=True)
            open(TOKEN_FILE, "w").write(str(r["restore_token"]))
        self.node = int(r["streams"][0][0])
        self.fd = sc.OpenPipeWireRemote(self.session, {}).take()
        return self

    def src(self):
        """GStreamer source description for this capture."""
        return f"pipewiresrc fd={self.fd} path={self.node} do-timestamp=true keepalive-time=100 always-copy=true"

    def close(self):
        try:
            self.bus.get_object("org.freedesktop.portal.Desktop", self.session).Close(
                dbus_interface="org.freedesktop.portal.Session")
        except Exception:
            pass
        try:
            os.close(self.fd)
        except Exception:
            pass


def default_monitor():
    """PulseAudio/PipeWire monitor source of the default sink (desktop audio)."""
    import subprocess
    sink = subprocess.run(["pactl", "get-default-sink"], capture_output=True, text=True).stdout.strip()
    return sink + ".monitor" if sink else None
