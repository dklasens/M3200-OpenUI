#!/usr/bin/env python3
"""Minimal QMI-over-QRTR client for the Inseego M3200 (SDX65).

Wire format confirmed via strace of modem2d:
  request:  [flags=0][txn u16][msgid u16][len u16][TLVs]
  response: [flags=1][txn u16][msgid u16][len u16][TLVs]
No svc/client bytes on the wire; the QRTR (node, port) identifies the service.
"""
import socket, struct

AF_QIPCRTR = 42
QRTR_PORT_CTRL = 0xFFFFFFFE
QRTR_TYPE_NEW_LOOKUP = 10
QRTR_TYPE_NEW_SERVER = 4

class QmiService:
    def __init__(self, sock, service_id, version=1):
        self.sock = sock
        self.service_id = service_id
        self.server = None
        self.txn = 0
        self.lookup(version)

    def lookup(self, version=1, instance=0):
        local = self.sock.getsockname()[0]
        # instance field on this firmware: low byte = version, high byte = instance id
        inst = (instance << 8) | version
        pkt = struct.pack("<IIIII", QRTR_TYPE_NEW_LOOKUP, self.service_id, inst, 0, 0)
        self.sock.sendto(pkt, (local, QRTR_PORT_CTRL))
        self.sock.settimeout(1.5)
        try:
            while True:
                data, addr = self.sock.recvfrom(4096)
                if len(data) < 20:
                    continue
                cmd, svc, ins, node, port = struct.unpack("<IIIII", data[:20])
                if cmd == QRTR_TYPE_NEW_SERVER:
                    if svc == 0 and node == 0 and port == 0:
                        break
                    if svc == self.service_id:
                        self.server = (node, port)
        except socket.timeout:
            pass

    def request(self, msgid, tlvs=b"", timeout=3.0):
        if not self.server:
            raise RuntimeError(f"service {self.service_id} not found")
        self.txn = (self.txn + 1) & 0xFFFF or 1
        hdr = struct.pack("<BHHH", 0, self.txn, msgid, len(tlvs))
        self.sock.sendto(hdr + tlvs, self.server)
        self.sock.settimeout(timeout)
        while True:
            data, addr = self.sock.recvfrom(4096)
            if addr != self.server:
                continue
            flags, txn, mid, ln = struct.unpack("<BHHH", data[:7])
            body = data[7:7+ln]
            if txn == self.txn and mid == msgid:
                return body
            # else: indication or mismatched txn -> keep waiting

def parse_tlvs(buf):
    out = {}
    i = 0
    while i + 3 <= len(buf):
        t, ln = buf[i], struct.unpack("<H", buf[i+1:i+3])[0]
        out.setdefault(t, []).append(buf[i+3:i+3+ln])
        i += 3 + ln
    return out

def tlv_result(tlvs):
    if 0x02 in tlvs:
        r, e = struct.unpack("<HH", tlvs[0x02][0][:4])
        return r, e
    return None, None

def connect():
    s = socket.socket(AF_QIPCRTR, socket.SOCK_DGRAM, 0)
    local = s.getsockname()[0]
    s.bind((local, 0))
    return s

if __name__ == "__main__":
    import sys
    s = connect()
    nas = QmiService(s, 3)
    dms = QmiService(s, 2)
    print("NAS server:", nas.server, "DMS server:", dms.server)

    RAT_MODES = {0:"1x",1:"EVDO",2:"GSM",3:"UMTS",4:"LTE",5:"TDSCDMA",6:"NR5G"}

    print("\n== GET_SYSTEM_SELECTION_PREFERENCE ==")
    body = nas.request(0x0034)
    tlvs = parse_tlvs(body)
    print("result:", tlv_result(tlvs))
    if 0x11 in tlvs:
        m = struct.unpack("<H", tlvs[0x11][0])[0]
        print(f"  mode pref 0x{m:04x}: {[RAT_MODES[b] for b in range(8) if m & (1<<b)]}")
    if 0x15 in tlvs:
        v = struct.unpack("<Q", tlvs[0x15][0])[0]
        bands = [b+1 for b in range(64) if v & (1<<b)]
        print(f"  LTE band pref (1-64): {bands}")
    if 0x23 in tlvs:
        masks = struct.unpack("<QQQQ", tlvs[0x23][0])
        bands = []
        for i, m in enumerate(masks):
            bands += [i*64+b+1 for b in range(64) if m & (1<<b)]
        print(f"  LTE band pref ext (1-256): {bands}")
    for tid, name in ((0x2C, "NR5G SA"), (0x2D, "NR5G NSA")):
        if tid in tlvs:
            masks = struct.unpack("<QQQQQQQQ", tlvs[tid][0])
            bands = []
            for i, m in enumerate(masks):
                bands += [i*64+b+1 for b in range(64) if m & (1<<b)]
            print(f"  {name} band pref: n{bands}")

    print("\n== GET_ENDC_CONFIG ==")
    body = nas.request(0x00E8)
    tlvs = parse_tlvs(body)
    print("result:", tlv_result(tlvs), {hex(k): [x.hex() for x in v] for k, v in tlvs.items() if k != 2})

    print("\n== DMS GET_BAND_CAPABILITY ==")
    body = dms.request(0x0045)
    tlvs = parse_tlvs(body)
    print("result:", tlv_result(tlvs))
    for t, vals in sorted(tlvs.items()):
        for v in vals:
            print(f"  tlv 0x{t:02x} len {len(v)}: {v.hex()}")
    # decode 0x10 (u64 gsm/cdma/wcdma/lte 1-64), 0x11 ext lte (seq of u64?), 0x12/0x13 nr5g
    def mask_list(buf, n):
        vals = struct.unpack("<" + "Q" * (len(buf) // 8), buf)
        bands = []
        for i, m in enumerate(vals):
            bands += [i * 64 + b + 1 for b in range(64) if m & (1 << b)]
        return bands
    if 0x10 in tlvs:
        print("  band cap 0x10:", mask_list(tlvs[0x10][0], 64))
    if 0x11 in tlvs:
        print("  LTE band cap ext:", mask_list(tlvs[0x11][0], 256))
    for tid, name in ((0x12, "NR5G NSA cap"), (0x13, "NR5G SA cap")):
        if tid in tlvs:
            print(f"  {name}:", mask_list(tlvs[tid][0], 512))
