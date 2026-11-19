"""Cast RECEIVER: makes this Linux box show up as a Google Cast device other phones/Chrome can cast to.
No browser involved. Advertises _googlecast._tcp, accepts the CastV2 TLS channel, negotiates the
mirroring OFFER/ANSWER, decrypts the incoming RTP video/audio and renders it full screen."""
import json, os, random, socket, ssl, struct, subprocess, threading, time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from .channel import encode, decode, NS_CONN, NS_HB, NS_RECV, NS_WEBRTC
from .receive_media import ReceiveMedia

APP_MIRRORING = "0F5096E8"
CFG = os.path.expanduser("~/.config/castdeck")


def ensure_cert():
    os.makedirs(CFG, exist_ok=True)
    crt, key = os.path.join(CFG, "receiver.crt"), os.path.join(CFG, "receiver.key")
    if not (os.path.exists(crt) and os.path.exists(key)):
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
                        "-keyout", key, "-out", crt, "-subj", "/CN=Castdeck"], check=True, capture_output=True)
    return crt, key


class _RtpUnwrap:
    """Expands the 8-bit frame id on the wire back into the sender's full monotonic counter."""
    def __init__(self):
        self.last = 0

    def expand(self, fid8):
        hi = self.last & ~0xFF
        best = min((hi - 256 + fid8, hi + fid8, hi + 256 + fid8), key=lambda c: abs(c - self.last))
        self.last = max(self.last, best)
        return best


class ReceiveStream:
    """One incoming media stream (video or audio): reassembles frames and decrypts them."""
    def __init__(self, info, on_frame, log):
        self.info, self.on_frame, self.log = info, on_frame, log
        self.key, self.mask = info["aesKey"], info["aesIvMask"]
        self.unwrap = _RtpUnwrap()
        self.parts = {}  # fid -> {pid: data}

    def _decrypt(self, fid, data):
        nonce = bytearray(16)
        nonce[8:12] = struct.pack(">I", fid & 0xFFFFFFFF)
        nonce = bytes(a ^ b for a, b in zip(nonce, self.mask))
        dec = Cipher(algorithms.AES(self.key), modes.CTR(nonce)).decryptor()
        return dec.update(data) + dec.finalize()

    def feed(self, pkt):
        # RTP header (12) + Cast header (7): see castnative/rtp.py StreamSender.send_frame for the wire format
        fid8, pid, maxpid, ref8 = pkt[13], struct.unpack(">H", pkt[14:16])[0], struct.unpack(">H", pkt[16:18])[0], pkt[18]
        payload = pkt[19:]
        fid = self.unwrap.expand(fid8)
        self.parts.setdefault(fid, {})[pid] = payload
        got = self.parts[fid]
        if len(got) == maxpid + 1:
            data = b"".join(got[i] for i in range(maxpid + 1))
            del self.parts[fid]
            try:
                self.on_frame(self._decrypt(fid, data))
            except Exception as e:
                self.log("decrypt/frame error:", e)
            stale = [f for f in self.parts if f < fid - 30]
            for f in stale:
                del self.parts[f]


class ReceiverSession:
    """One connected sender (phone/Chrome): channel + UDP media socket for the lifetime of a cast."""
    def __init__(self, sock, media, log, fullscreen=True):
        self.sock, self.media, self.log, self.fullscreen = sock, media, log, fullscreen
        self.alive = True
        self.udp = None
        self.transport_id = "recv-%d" % random.randrange(1 << 20)
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, ns, payload, dst, src="receiver-0"):
        try:
            self.sock.sendall(encode(src, dst, ns, payload))
        except OSError:
            self.alive = False

    def _run(self):
        buf = b""
        try:
            while self.alive:
                d = self.sock.recv(65536)
                if not d:
                    break
                buf += d
                while len(buf) >= 4:
                    n = int.from_bytes(buf[:4], "big")
                    if len(buf) < 4 + n:
                        break
                    m = decode(buf[4:4 + n]); buf = buf[4 + n:]
                    self._handle(m.get(4, b"").decode(), m.get(2, b"").decode(), json.loads(m.get(6, b"{}").decode() or "{}"))
        except Exception as e:
            self.log("receiver session ended:", e)
        self.alive = False
        if self.udp:
            self.udp.close()
        self.media.stop()

    def _handle(self, ns, src, pl):
        t = pl.get("type")
        if ns == NS_HB and t == "PING":
            self.send(NS_HB, {"type": "PONG"}, src)
        elif ns == NS_RECV and t in ("GET_STATUS", "LAUNCH"):
            self.send(NS_RECV, {"type": "RECEIVER_STATUS", "requestId": pl.get("requestId", 0),
                                "status": {"applications": [{"appId": APP_MIRRORING, "displayName": "Chrome Mirroring",
                                           "transportId": self.transport_id, "namespaces": [{"name": NS_WEBRTC}, {"name": NS_CONN}],
                                           "statusText": "Castdeck receiver"}]}}, src)
        elif ns == NS_WEBRTC and t == "OFFER":
            self._offer(pl, src)
        elif ns == NS_RECV and t == "STOP":
            self.alive = False

    def _offer(self, pl, src):
        streams = pl["offer"]["supportedStreams"]
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp.bind(("0.0.0.0", 0))
        port = self.udp.getsockname()[1]
        send_indexes, ssrcs, by_ssrc = [], [], {}
        vid = [s for s in streams if s["type"] == "video_source"]
        aud = [s for s in streams if s["type"] == "audio_source"]
        if vid:
            self.media.start_video(fullscreen=self.fullscreen)
        if aud:
            self.media.start_audio()
        for s in streams:
            s["aesKey"] = bytes.fromhex(s["aesKey"]); s["aesIvMask"] = bytes.fromhex(s["aesIvMask"])
            on_frame = self.media.push_video if s["type"] == "video_source" else self.media.push_audio
            rs = ReceiveStream(s, on_frame, self.log)
            by_ssrc[s["ssrc"]] = rs
            send_indexes.append(s["index"]); ssrcs.append(random.randrange(10000, 99999))
        threading.Thread(target=self._rx_loop, args=(by_ssrc,), daemon=True).start()
        self.send(NS_WEBRTC, {"type": "ANSWER", "seqNum": pl.get("seqNum", 1), "result": "ok",
                              "answer": {"udpPort": port, "sendIndexes": send_indexes, "ssrcs": ssrcs,
                                         "receiverRtcpEventLog": [], "receiverGetStatus": True}}, src)
        self.log(f"accepted offer: {len(streams)} stream(s), listening on udp {port}")

    def _rx_loop(self, by_ssrc):
        self.udp.settimeout(0.5)
        while self.alive:
            try:
                data, addr = self.udp.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(data) < 19:
                continue
            ssrc = struct.unpack(">I", data[8:12])[0]
            rs = by_ssrc.get(ssrc)
            if rs:
                rs.feed(data)


class CastReceiver:
    """Advertises this host as a Cast device and accepts incoming mirroring sessions."""
    def __init__(self, name="Castdeck", log=print):
        self.name, self.log = name, log
        self._avahi = None
        self._srv = None

    def _advertise(self):
        uid = "%032x" % random.getrandbits(128)
        txt = ["id=" + uid, "ve=05", "md=Castdeck", "ic=/setup/icon.png", "fn=" + self.name, "ca=4101", "st=0", "rs="]
        args = ["avahi-publish-service", self.name, "_googlecast._tcp", "8009"] + txt
        self._avahi = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start(self, advertise=True, bind="0.0.0.0", fullscreen=True):
        self.fullscreen = fullscreen
        crt, key = ensure_cert()
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(crt, key)
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw.bind((bind, 8009))
        raw.listen(5)
        self._srv = ctx.wrap_socket(raw, server_side=True)
        if advertise:
            self._advertise()
        self.log(f"Cast receiver '{self.name}' listening on 8009" + (", advertised on the network" if advertise else ""))
        while True:
            try:
                conn, addr = self._srv.accept()
            except OSError:
                return
            self.log("sender connected from", addr)
            ReceiverSession(conn, ReceiveMedia(log=self.log), self.log, fullscreen=self.fullscreen)

    def stop(self):
        if self._avahi:
            self._avahi.terminate()
        if self._srv:
            self._srv.close()


if __name__ == "__main__":
    import sys
    CastReceiver(sys.argv[1] if len(sys.argv) > 1 else "Castdeck").start()
