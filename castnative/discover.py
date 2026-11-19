"""Find Google Cast receivers on the LAN via Avahi (mDNS _googlecast._tcp)."""
import subprocess


def discover(timeout=6):
    """Return [{'name','host','port'}]."""
    try:
        out = subprocess.run(["avahi-browse", "-rtp", "_googlecast._tcp"], capture_output=True,
                             text=True, timeout=timeout + 10).stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    seen = {}
    for ln in out.splitlines():
        f = ln.split(";")
        if f[0] != "=" or len(f) < 10 or f[2] != "IPv4":
            continue
        txt = {k: v for k, _, v in (t.strip('"').partition("=") for t in f[9].split('" "'))}
        name = txt.get("fn") or f[3]
        seen[name] = {"name": name, "host": f[7], "port": int(f[8]), "model": txt.get("md", "")}
    return list(seen.values())


def find(name_substr=""):
    for d in discover():
        if name_substr.lower() in d["name"].lower():
            return d
    return None
