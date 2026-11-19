"""GStreamer capture + encode pipelines that hand encoded frames to callbacks."""
import threading, time
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib

Gst.init(None)


def encoder_name(prefer="auto"):
    for n in (["vah264enc", "x264enc"] if prefer in ("auto", "hw") else ["x264enc"]):
        if Gst.ElementFactory.find(n):
            return n
    raise RuntimeError("no H.264 encoder found")


def video_encode_chain(width, height, fps, bitrate_kbps, enc=None):
    enc = enc or encoder_name()
    scale = (f"videoconvert ! videoscale add-borders=true ! videorate ! "
             f"video/x-raw,width={width},height={height},framerate={fps}/1,pixel-aspect-ratio=1/1 ! ")
    if enc == "x264enc":
        e = (f"x264enc tune=zerolatency speed-preset=veryfast bitrate={bitrate_kbps} key-int-max={fps*2} "
             f"bframes=0 byte-stream=true ! video/x-h264,profile=main")
    else:  # vah264enc
        e = f"vah264enc bitrate={bitrate_kbps} key-int-max={fps*2} b-frames=0 rate-control=cbr ! video/x-h264,profile=main"
    return (scale + e + " ! h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! appsink name=vsink emit-signals=true sync=false max-buffers=4 drop=true")


class Media:
    def __init__(self, on_video, on_audio, log=print):
        self.on_video, self.on_audio, self.log = on_video, on_audio, log
        self.vp = self.ap = None
        self.t0 = None
        self.loop = GLib.MainLoop()

    def _hook(self, pipeline, sink_name, cb):
        sink = pipeline.get_by_name(sink_name)

        def new_sample(s):
            smp = s.emit("pull-sample")
            buf = smp.get_buffer()
            ok, info = buf.map(Gst.MapFlags.READ)
            if ok:
                data = bytes(info.data)
                buf.unmap(info)
                pts = (buf.pts / 1e9) if buf.pts != Gst.CLOCK_TIME_NONE else (time.monotonic() - self.t0)
                key = not buf.has_flags(Gst.BufferFlags.DELTA_UNIT)
                cb(data, pts, key)
            return Gst.FlowReturn.OK
        sink.connect("new-sample", new_sample)

    def start(self, video_src, audio_src, width, height, fps, vbitrate_kbps, enc=None):
        self.vp = Gst.parse_launch(f"{video_src} ! queue max-size-buffers=3 leaky=downstream ! "
                                   + video_encode_chain(width, height, fps, vbitrate_kbps, enc)) if video_src else None
        self.ap = Gst.parse_launch(f"{audio_src} ! audioconvert ! audioresample ! "
                                   "audio/x-raw,rate=48000,channels=2 ! opusenc frame-size=20 bitrate=128000 ! "
                                   "appsink name=asink emit-signals=true sync=false") if audio_src else None
        self.t0 = time.monotonic()
        if self.vp:
            self._hook(self.vp, "vsink", self.on_video)
            self.vp.set_state(Gst.State.PLAYING)
        if self.ap:
            self._hook(self.ap, "asink", lambda d, p, k: self.on_audio(d, p, True))
            self.ap.set_state(Gst.State.PLAYING)
        threading.Thread(target=self.loop.run, daemon=True).start()

    def force_keyframe(self):
        if self.vp:
            ev = Gst.Event.new_custom(Gst.EventType.CUSTOM_UPSTREAM,
                                      Gst.Structure.new_from_string("GstForceKeyUnit, all-headers=(boolean)true"))
            self.vp.send_event(ev)

    def stop(self):
        for p in (self.vp, self.ap):
            if p:
                p.set_state(Gst.State.NULL)
        self.loop.quit()
