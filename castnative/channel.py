"""CastV2 control channel: TLS to port 8009, length-prefixed CastMessage protobufs (hand-encoded)."""
import json, socket, ssl, threading, time, queue

NS_CONN = "urn:x-cast:com.google.cast.tp.connection"
NS_HB = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECV = "urn:x-cast:com.google.cast.receiver"
NS_WEBRTC = "urn:x-cast:com.google.cast.webrtc"


def _varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _rvarint(b, i):
    r = s = 0
    while True:
        c = b[i]; i += 1
        r |= (c & 0x7F) << s; s += 7
        if not c & 0x80:
            return r, i


def _fstr(num, s):
    b = s.encode()
    return _varint(num << 3 | 2) + _varint(len(b)) + b


def encode(src, dst, ns, payload):
    m = _varint(1 << 3) + _varint(0) + _fstr(2, src) + _fstr(3, dst) + _fstr(4, ns)
    m += _varint(5 << 3) + _varint(0) + _fstr(6, json.dumps(payload))
    return len(m).to_bytes(4, "big") + m


def decode(b):
    i, f = 0, {}
    while i < len(b):
        k, i = _rvarint(b, i)
        fn, wt = k >> 3, k & 7
        if wt == 0:
            v, i = _rvarint(b, i)
        elif wt == 2:
            n, i = _rvarint(b, i); v = b[i:i + n]; i += n
        else:
            break
        f[fn] = v
    return f


class CastChannel:
    def __init__(self, host, port=8009, log=None):
        self.host, self.log = host, log or (lambda *a: None)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE      # Cast devices use self-signed certificates
        self.sock = ctx.wrap_socket(socket.create_connection((host, port), timeout=10), server_hostname=host)
        self.sock.settimeout(None)
        self.inbox = queue.Queue()
        self.alive = True
        self._lock = threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()

    def send(self, ns, payload, dst="receiver-0", src="sender-0"):
        with self._lock:
            self.sock.sendall(encode(src, dst, ns, payload))

    def _heartbeat(self):
        while self.alive:
            time.sleep(4)
            try:
                self.send(NS_HB, {"type": "PING"})
            except Exception:
                self.alive = False

    def _reader(self):
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
                    ns = m.get(4, b"").decode()
                    try:
                        pl = json.loads(m.get(6, b"{}").decode())
                    except Exception:
                        pl = {}
                    if ns == NS_HB and pl.get("type") == "PING":
                        self.send(NS_HB, {"type": "PONG"}, dst=m.get(2, b"").decode())
                    elif ns != NS_HB:
                        self.inbox.put((ns, m.get(2, b"").decode(), pl))
        except Exception as e:
            self.log("channel reader ended:", e)
        self.alive = False
        self.inbox.put(None)

    def wait(self, match, timeout=10):
        """Return the first inbound (ns, src, payload) for which match(ns, src, payload) is true."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                item = self.inbox.get(timeout=max(0.05, end - time.time()))
            except queue.Empty:
                break
            if item is None:
                raise ConnectionError("Cast channel closed")
            if match(*item):
                return item
        raise TimeoutError("no matching Cast message")

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass
