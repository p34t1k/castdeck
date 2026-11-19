"""Cast a live desktop to a receiver, with supervision (no browser involved)."""
import threading, time
from .session import MirroringSession
from .rtp import Transport
from .media import Media
from . import capture, discover


class Caster:
    def __init__(self, host, width=1920, height=1080, fps=30, vbitrate=6000, audio=True, log=print):
        self.host, self.w, self.h, self.fps, self.vb, self.audio, self.log = host, width, height, fps, vbitrate, audio, log
        self.stop_ev = threading.Event()
        self.state = "idle"

    def _once(self, portal):
        sess = MirroringSession(self.host, log=self.log).start(
            video=True, audio=self.audio, width=self.w, height=self.h, fps=self.fps,
            vbitrate=self.vb * 1000)
        tr = Transport(self.host, sess.udp_port, log=self.log)
        media = Media(None, None, log=self.log)
        vs = au = None
        for s in sess.streams:
            snd = tr.add(ssrc=s.ssrc, payload_type=s.pt, clock_rate=s.clock, aes_key=s.aes_key,
                         iv_mask=s.iv_mask, is_video=s.kind == "video", receiver_ssrc=s.receiver_ssrc,
                         on_keyframe_request=media.force_keyframe if s.kind == "video" else None)
            if s.kind == "video":
                vs = snd
            else:
                au = snd
        media.on_video = lambda d, p, k: vs.send_frame(d, p, k)
        media.on_audio = lambda d, p, k: au.send_frame(d, p, True) if au else None
        mon = capture.default_monitor() if au else None
        media.start(portal.src(), f"pulsesrc device={mon}" if mon else None, self.w, self.h, self.fps, self.vb)
        self.state = "casting"
        self.log("casting")
        last, stall = vs.stats["frames"], time.time()
        try:
            while not self.stop_ev.is_set():
                time.sleep(2)
                if not sess.ch.alive:
                    raise RuntimeError("receiver connection lost")
                if vs.stats["frames"] != last:
                    last, stall = vs.stats["frames"], time.time()
                elif time.time() - stall > 20:
                    raise RuntimeError("no video frames for 20 s")
        finally:
            media.stop()
            tr.close()
            sess.stop()

    def run(self, retries=1000):
        portal = capture.Portal().open()
        try:
            for attempt in range(retries + 1):
                self.state = "connecting"
                try:
                    self._once(portal)
                    return
                except Exception as e:
                    if self.stop_ev.is_set():
                        return
                    self.log(f"dropped: {e}; reconnecting in 5 s")
                    self.state = "reconnecting"
                    self.stop_ev.wait(5)
        finally:
            portal.close()
            self.state = "idle"

    def stop(self):
        self.stop_ev.set()
