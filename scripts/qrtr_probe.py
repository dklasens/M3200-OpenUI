#!/usr/bin/env python3
# QRTR service scanner + QMI-over-QRTR probe for the M3200 (SDX65).
import socket, struct, sys

AF_QIPCRTR = 42
QRTR_PORT_CTRL = 0xFFFFFFFE
QRTR_TYPE_DATA = 1
QRTR_TYPE_NEW_SERVER = 4
QRTR_TYPE_NEW_LOOKUP = 10

QMI_SVC = {0:"CTL",1:"WDS",2:"DMS",3:"NAS",4:"QOS",5:"WMS",6:"PDS",7:"AUTH",
           9:"AT",10:"VOICE",11:"CAT2",12:"UIM",13:"PBM",16:"SAR",17:"IMS",
           18:"ADC",19:"RMS",20:"OTA",23:"RFRPE",24:"DSD",26:"SSCTL",27:"IMSP",
           28:"IMSS",29:"GPS",31:"CAT",34:"IMSA",36:"LWM2M",37:"WLMS",
           0x0A:"?", 0x2F:"?", 0xE0:"?", 0xE1:"?", 0xE2:"?", 0xE3:"?",
           0xE4:"?", 0xE5:"?", 0xE6:"?", 0xE7:"?", 0xE8:"?", 0xE9:"?",
           0xEA:"?", 0xEB:"?", 0xEC:"?", 0xED:"?", 0xEE:"?", 0xEF:"?",
           0xF0:"?", 0xF1:"?", 0xF2:"?", 0xF3:"?", 0xF4:"?", 0xF5:"?",
           0xF6:"?", 0xF7:"?", 0xF8:"?", 0xF9:"?", 0xFA:"?", 0xFB:"?",
           0xFC:"?", 0xFD:"?", 0xFE:"?", 0xFF:"SWI?"}

def scan(sock):
    """Wildcard lookup: service=0 instance=0 -> dump every server."""
    pkt = struct.pack("<IIIII", QRTR_TYPE_NEW_LOOKUP, 0, 0, 0, 0)
    sock.sendto(pkt, (LOCAL_NODE, QRTR_PORT_CTRL))
    servers = []
    sock.settimeout(2)
    try:
        while True:
            data, addr = sock.recvfrom(4096)
            if len(data) < 20:
                continue
            cmd, svc, inst, node, port = struct.unpack("<IIIII", data[:20])
            if cmd == QRTR_TYPE_NEW_SERVER and svc == 0 and node == 0 and port == 0:
                break  # end-of-listing terminator
            if cmd in (QRTR_TYPE_NEW_SERVER,):
                servers.append((svc, inst, node, port))
    except socket.timeout:
        pass
    return servers

def qmi_send_recv(sock, server, service, client, txn, msgid, tlvs=b""):
    hdr = struct.pack("<BBBHHH", service, client, 0, txn, msgid, len(tlvs))
    sock.sendto(hdr + tlvs, server)
    sock.settimeout(2.5)
    while True:
        data, addr = sock.recvfrom(4096)
        if addr == server:
            return data

def main():
    global LOCAL_NODE
    s = socket.socket(AF_QIPCRTR, socket.SOCK_DGRAM, 0)
    LOCAL_NODE = s.getsockname()[0]
    s.bind((LOCAL_NODE, 0))
    print(f"local node {LOCAL_NODE}, port {s.getsockname()[1]}")

    servers = scan(s)
    print(f"\n== {len(servers)} QRTR servers ==")
    bysvc = {}
    for svc, inst, node, port in sorted(servers):
        name = QMI_SVC.get(svc, "?")
        print(f"  svc 0x{svc:02x} ({name:6s}) ver {inst>>8}.{inst&0xff} inst {(inst>>8)&0xff}.{inst&0xff} @ node {node} port {port}")
        bysvc.setdefault(svc, []).append((inst, node, port))

    if 3 in bysvc:
        inst, node, port = bysvc[3][0]
        print(f"\n== NAS found @ node {node} port {port}; trying GET_SIGNAL_INFO with cid=0 ==")
        try:
            resp = qmi_send_recv(s, (node, port), 3, 0, 1, 0x004F)
            print("resp:", resp.hex())
        except socket.timeout:
            print("no reply with cid=0; will need CTL CID allocation")

if __name__ == "__main__":
    main()
