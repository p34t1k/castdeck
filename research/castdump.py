#!/usr/bin/env python3
"""Dump decrypted CastV2 messages from a pcap + TLS keylog:  castdump.py pcap keylog"""
import subprocess, sys, json
pcap, keys = sys.argv[1], sys.argv[2]
out = subprocess.run(["tshark","-r",pcap,"-o",f"tls.keylog_file:{keys}","-Y","tcp.port==8009 && tls.app_data && tcp.port==46428",
  "-T","fields","-e","frame.time_relative","-e","ip.src","-e","tcp.srcport","-e","tls.app_data"],capture_output=True,text=True).stdout
def varint(b,i):
    r=s=0
    while True:
        c=b[i]; i+=1; r|=(c&0x7f)<<s; s+=7
        if not c&0x80: return r,i
def parse(b):
    i=0; f={}
    while i<len(b):
        k,i=varint(b,i); fn,wt=k>>3,k&7
        if wt==0: v,i=varint(b,i)
        elif wt==2: l,i=varint(b,i); v=b[i:i+l]; i+=l
        else: break
        f[fn]=v
    return f
bufs={}
for line in out.splitlines():
    p=line.split("\t")
    if len(p)<4: continue
    t,src,sp,data=p[0],p[1],p[2],p[3]
    key=(src,sp)
    b=bufs.setdefault(key,b"")+b"".join(bytes.fromhex(x.replace(":","")) for x in data.split(","))
    while len(b)>=4:
        n=int.from_bytes(b[:4],"big")
        if len(b)<4+n: break
        try: m=parse(b[4:4+n])
        except Exception: bufs[key]=b""; b=b""; break
        b=b[4+n:]
        pl=m.get(6,b"").decode(errors="replace") if 6 in m else f"<binary {len(m.get(7,b''))}B>"
        who="PANEL->" if src=="192.168.1.45" else "LAPTOP->"
        print(f"{float(t):7.2f} {who} {m.get(4,b'').decode()} [{m.get(2,b'').decode()}→{m.get(3,b'').decode()}] {pl[:1500]}")
    bufs[key]=b
