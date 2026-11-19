"""Cast Streaming RTP/RTCP sender (format per Google's open-source openscreen)."""
import collections, random, socket, struct, threading, time
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAX_PACKET = 1200          # whole RTP packet, conservative for Wi-Fi
RTP_HDR, CAST_HDR = 12, 7  # base RTP header, base Cast header (no extensions)
MAX_PAYLOAD = MAX_PACKET - RTP_HDR - CAST_HDR
NTP_EPOCH_OFFSET = 2208988800
ALL_PACKETS_LOST = 0xFFFF


def ntp_now():
    t = time.time() + NTP_EPOCH_OFFSET
    sec = int(t)
    return (sec << 32) | int((t - sec) * (1 << 32)) & 0xFFFFFFFF


class StreamSender:
    """One Cast RTP stream (video or audio) towards the receiver's UDP port."""

    def __init__(self, sock, addr, ssrc, payload_type, clock_rate, aes_key, iv_mask,
                 is_video, receiver_ssrc=None, on_keyframe_request=None, log=None):
        self.sock, self.addr, self.ssrc, self.pt = sock, addr, ssrc, payload_type
        self.clock, self.key, self.mask, self.is_video = clock_rate, aes_key, iv_mask, is_video
        self.receiver_ssrc = receiver_ssrc
        self.on_keyframe_request = on_keyframe_request or (lambda: None)
        self.log = log or (lambda *a: None)
        self.seq = random.randrange(65536)
        self.frame_id = 0
        self.packets = 0
        self.octets = 0
        self.cache = collections.OrderedDict()           # (frame_id, packet_id) -> bytes
        self.base_rtp = random.randrange(1 << 32)
        self.last_rtp = self.base_rtp
        self.stats = {"frames": 0, "retx": 0, "plis": 0, "ckpt": -1, "feedbacks": 0}
        self._lock = threading.Lock()

    # ---- encryption: AES-128-CTR, nonce = frame_id (bytes 8..11) XOR iv_mask --------------
    def _crypt(self, frame_id, data):
        nonce = bytearray(16)
        nonce[8:12] = struct.pack(">I", frame_id & 0xFFFFFFFF)
        nonce = bytes(a ^ b for a, b in zip(nonce, self.mask))
        enc = Cipher(algorithms.AES(self.key), modes.CTR(nonce)).encryptor()
        return enc.update(data) + enc.finalize()

    # ---- sending frames --------------------------------------------------------------
    def send_frame(self, data, pts_seconds, key_frame=True):
        """data: encoded frame (H.264 Annex B / Opus packet). pts_seconds: capture time since start."""
        with self._lock:
            fid = self.frame_id
            self.frame_id += 1
            rtp_ts = (self.base_rtp + int(pts_seconds * self.clock)) & 0xFFFFFFFF
            self.last_rtp, self.last_rtp_wall = rtp_ts, time.time()
            ref = fid if key_frame else fid - 1
            enc = self._crypt(fid, data)
            n = max(1, -(-len(enc) // MAX_PAYLOAD))
            for pid in range(n):
                chunk = enc[pid * MAX_PAYLOAD:(pid + 1) * MAX_PAYLOAD]
                marker = 0x80 if pid == n - 1 else 0
                pkt = struct.pack(">BBHII", 0x80, marker | self.pt, self.seq & 0xFFFF, rtp_ts, self.ssrc)
                pkt += struct.pack(">BBHHB", (0x80 if key_frame else 0) | 0x40, fid & 0xFF, pid, n - 1, ref & 0xFF)
                pkt += chunk
                self.seq += 1
                self.sock.sendto(pkt, self.addr)
                self.packets += 1
                self.octets += len(chunk)
                self.cache[(fid & 0xFF, pid)] = pkt
            while len(self.cache) > 1500:
                self.cache.popitem(last=False)
            self.stats["frames"] += 1

    # ---- RTCP ------------------------------------------------------------------------
    def send_sender_report(self):
        if not self.stats["frames"]:
            return
        # extrapolate the RTP timestamp of "now" from the latest frame
        rtp = (self.last_rtp + int((time.time() - self.last_rtp_wall) * self.clock)) & 0xFFFFFFFF
        sr = struct.pack(">BBH", 0x80, 200, 6) + struct.pack(">IQIII", self.ssrc, ntp_now(), rtp,
                                                              self.packets & 0xFFFFFFFF, self.octets & 0xFFFFFFFF)
        self.sock.sendto(sr, self.addr)

    def handle_rtcp(self, sub, pt, body):
        """Handle one RTCP sub-packet (already matched to this stream by media SSRC)."""
        if pt == 206 and sub == 1:                             # PSFB / Picture Loss Indicator
            self.stats["plis"] += 1
            self.on_keyframe_request()
        elif pt == 206 and sub == 15 and len(body) >= 16 and body[4:8] == struct.pack(">I", self.ssrc) \
                and body[8:12] == b"CAST":
            self._cast_feedback(body)

    def _cast_feedback(self, body):
        ckpt, nloss = body[12], body[13]
        self.stats["ckpt"] = ckpt
        self.stats["feedbacks"] += 1
        off = 16
        for _ in range(nloss):
            if off + 4 > len(body):
                break
            fid, pid, bits = body[off], struct.unpack(">H", body[off + 1:off + 3])[0], body[off + 3]
            off += 4
            if pid == ALL_PACKETS_LOST:
                lost = [k for k in self.cache if k[0] == fid]
            else:
                lost = [(fid, pid)] + [(fid, pid + 1 + b) for b in range(8) if bits & (1 << b)]
            for k in lost:
                p = self.cache.get(k)
                if p:
                    self.sock.sendto(p, self.addr)
                    self.stats["retx"] += 1
        # pycache of ACK bit-vector (CST2) is not needed for correctness here


class Transport:
    """UDP socket shared by the streams of a session + RTCP receive/SR timers."""

    def __init__(self, host, port, log=None):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)
        self.addr = (host, port)
        self.streams = {}
        self.log = log or (lambda *a: None)
        self.running = True
        threading.Thread(target=self._rx, daemon=True).start()
        threading.Thread(target=self._sr_timer, daemon=True).start()

    def add(self, **kw):
        s = StreamSender(self.sock, self.addr, log=self.log, **kw)
        self.streams[s.ssrc] = s
        return s

    def _rx(self):
        self.sock.settimeout(0.5)
        while self.running:
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            self._dispatch(data)

    def _dispatch(self, data):
        """Split a compound RTCP packet and route each sub-packet by its media (sender) SSRC."""
        i = 0
        while i + 4 <= len(data) and 200 <= data[i + 1] <= 207:
            sub, pt = data[i] & 0x1F, data[i + 1]
            words = struct.unpack(">H", data[i + 2:i + 4])[0]
            body = data[i + 4:i + 4 + words * 4]
            i += 4 + words * 4
            if pt in (205, 206) and len(body) >= 8:
                st = self.streams.get(struct.unpack(">I", body[4:8])[0])
                if st:
                    st.handle_rtcp(sub, pt, body)

    def _sr_timer(self):
        while self.running:
            time.sleep(1)
            for s in self.streams.values():
                try:
                    s.send_sender_report()
                except OSError:
                    pass

    def close(self):
        self.running = False
        self.sock.close()
