"""Decode + render pipelines for the Cast RECEIVER: appsrc (fed decrypted frames) -> decode -> screen/speakers."""
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import threading

Gst.init(None)


class ReceiveMedia:
    """Feeds decrypted H.264 Annex-B frames and Opus packets into GStreamer for full-screen playback."""

    def __init__(self, log=print):
        self.log = log
        self.vp = self.ap = None
        self.vsrc = self.asrc = None
        self.loop = GLib.MainLoop()
        self._thread = threading.Thread(target=self.loop.run, daemon=True)
        self._thread.start()

    def start_video(self, fullscreen=True):
        sink = "waylandsink fullscreen=true" if fullscreen else "autovideosink"
        desc = (f"appsrc name=vsrc is-live=true format=time do-timestamp=true caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
                f"h264parse ! avdec_h264 ! videoconvert ! {sink}")
        self.vp = Gst.parse_launch(desc)
        self.vsrc = self.vp.get_by_name("vsrc")
        self.vp.get_bus().add_signal_watch()
        self.vp.get_bus().connect("message", self._bus_msg, "video")
        self.vp.set_state(Gst.State.PLAYING)

    def start_audio(self):
        desc = ("appsrc name=asrc is-live=true format=time do-timestamp=true "
                "caps=audio/x-opus,channels=(int)2,rate=(int)48000,channel-mapping-family=(int)0 ! "
                "opusdec plc=true ! audioconvert ! audioresample ! autoaudiosink")
        self.ap = Gst.parse_launch(desc)
        self.asrc = self.ap.get_by_name("asrc")
        self.ap.get_bus().add_signal_watch()
        self.ap.get_bus().connect("message", self._bus_msg, "audio")
        self.ap.set_state(Gst.State.PLAYING)

    def _bus_msg(self, bus, msg, tag):
        if msg.type == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error(); self.log(f"{tag} pipeline ERROR: {err} ({dbg})")
        elif msg.type == Gst.MessageType.WARNING:
            err, dbg = msg.parse_warning(); self.log(f"{tag} pipeline WARNING: {err} ({dbg})")

    def push_video(self, data):
        if self.vsrc:
            self.vsrc.emit("push-buffer", Gst.Buffer.new_wrapped(bytes(data)))

    def push_audio(self, data):
        if self.asrc:
            self.asrc.emit("push-buffer", Gst.Buffer.new_wrapped(bytes(data)))

    def stop(self):
        for p in (self.vp, self.ap):
            if p:
                p.set_state(Gst.State.NULL)
        self.loop.quit()
