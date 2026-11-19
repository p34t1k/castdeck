"""Cast mirroring session: launch the receiver's mirroring app, negotiate streams (OFFER/ANSWER)."""
import os, random
from .channel import CastChannel, NS_CONN, NS_RECV, NS_WEBRTC

APP_MIRRORING = "0F5096E8"        # "Chrome Mirroring" (video + audio)
APP_AUDIO_ONLY = "85CDB22F"


class Stream:
    def __init__(self, kind, index, ssrc, pt, clock, codec, aes_key, iv_mask, **extra):
        self.kind, self.index, self.ssrc, self.pt, self.clock = kind, index, ssrc, pt, clock
        self.codec, self.aes_key, self.iv_mask, self.extra = codec, aes_key, iv_mask, extra
        self.receiver_ssrc = None

    def offer(self, target_delay):
        d = {"index": self.index, "type": f"{self.kind}_source", "codecName": self.codec,
             "rtpProfile": "cast", "rtpPayloadType": self.pt, "ssrc": self.ssrc,
             "timeBase": f"1/{self.clock}", "aesKey": self.aes_key.hex(), "aesIvMask": self.iv_mask.hex(),
             "targetDelay": target_delay, "receiverRtcpEventLog": True}
        if self.kind == "video":
            d.update({"maxFrameRate": f"{self.extra.get('fps', 30)}/1", "maxBitRate": self.extra.get("bitrate", 6_000_000),
                      "resolutions": [{"width": self.extra.get("width", 1920), "height": self.extra.get("height", 1080)}],
                      "protection": "", "profile": "", "level": ""})
        else:
            d.update({"channels": self.extra.get("channels", 2), "bitRate": self.extra.get("bitrate", 128000)})
        return d


class MirroringSession:
    def __init__(self, host, log=print):
        self.host, self.log = host, log
        self.ch = None
        self.transport = None
        self.udp_port = None
        self.streams = []
        self._req = 0

    def _rid(self):
        self._req += 1
        return self._req

    def start(self, video=True, audio=True, width=1920, height=1080, fps=30,
              vbitrate=6_000_000, target_delay=400, app_id=APP_MIRRORING):
        self.ch = CastChannel(self.host, log=self.log)
        self.ch.send(NS_CONN, {"type": "CONNECT", "userAgent": "castnative"})
        rid = self._rid()
        self.ch.send(NS_RECV, {"type": "LAUNCH", "appId": app_id, "requestId": rid})

        def launched(ns, src, pl):
            return pl.get("type") == "RECEIVER_STATUS" and any(
                a.get("appId") == app_id for a in pl.get("status", {}).get("applications", []))
        _, _, pl = self.ch.wait(launched, timeout=15)
        app = [a for a in pl["status"]["applications"] if a.get("appId") == app_id][0]
        self.transport = app["transportId"]
        self.log(f"launched '{app.get('displayName')}' transport={self.transport}")
        self.ch.send(NS_CONN, {"type": "CONNECT", "userAgent": "castnative"}, dst=self.transport)

        r = random.SystemRandom()
        idx = 0
        if video:
            self.streams.append(Stream("video", idx, 1000 + r.randrange(10) * 2, 96, 90000, "h264",
                                       os.urandom(16), os.urandom(16), width=width, height=height,
                                       fps=fps, bitrate=vbitrate)); idx += 1
        if audio:
            self.streams.append(Stream("audio", idx, 3000 + r.randrange(10) * 2, 127, 48000, "opus",
                                       os.urandom(16), os.urandom(16), channels=2, bitrate=128000))
        offer = {"type": "OFFER", "seqNum": 1, "offer": {"castMode": "mirroring",
                 "supportedStreams": [s.offer(target_delay) for s in self.streams]}}
        self.ch.send(NS_WEBRTC, offer, dst=self.transport)
        _, _, ans = self.ch.wait(lambda ns, src, p: p.get("type") == "ANSWER", timeout=15)
        if ans.get("result") != "ok":
            raise RuntimeError(f"receiver rejected the offer: {ans}")
        a = ans["answer"]
        self.udp_port = a["udpPort"]
        for i, ssrc in zip(a["sendIndexes"], a["ssrcs"]):
            self.streams[i].receiver_ssrc = ssrc
        self.log(f"answer ok: udp={self.udp_port} sendIndexes={a['sendIndexes']} receiver ssrcs={a['ssrcs']}")
        return self

    def stop(self):
        try:
            if self.ch and self.ch.alive:
                self.ch.send(NS_RECV, {"type": "STOP", "sessionId": self.transport, "requestId": self._rid()})
                import time; time.sleep(0.3)
        except Exception:
            pass
        if self.ch:
            self.ch.close()
