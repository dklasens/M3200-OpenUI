#!/usr/bin/env python3
"""M3200-OpenUI: minimal QMI-over-QRTR client for the Inseego M3200 (SDX65).

Pure stdlib. No CID allocation needed: the QRTR (node, port) identifies the
service, so the wire format is just:

  request : [flags=0x00][txn u16][msgid u16][len u16][TLVs]
  response: [flags=0x01][txn u16][msgid u16][len u16][TLVs]
  TLV     : [type u8][len u16][payload]

Service discovery via the kernel QRTR nameserver at (local_node, 0xFFFFFFFE).
Instance field encoding on this firmware: (instance_id << 8) | version.

All decoders verified against live traffic and the libqmi NAS/DMS schemas.
Band preference writes are constrained to the capabilities reported by DMS and
use NAS Set System Selection Preference (0x0033).
"""
import socket
import struct
import threading
import time

AF_QIPCRTR = 42
QRTR_PORT_CTRL = 0xFFFFFFFE
_QRTR_TYPE_NEW_LOOKUP = 10
_QRTR_TYPE_NEW_SERVER = 4

# QMI service ids
SVC_DMS = 2
SVC_NAS = 3

# NAS message ids
NAS_GET_SIGNAL_INFO = 0x004F
NAS_GET_SYSTEM_INFO = 0x004D
NAS_GET_CELL_LOCATION_INFO = 0x0043
NAS_GET_LTE_CPHY_CA_INFO = 0x00AC
NAS_SET_SYSTEM_SELECTION_PREFERENCE = 0x0033
NAS_GET_SYSTEM_SELECTION_PREFERENCE = 0x0034
NAS_GET_ENDC_CONFIG = 0x00E8

# DMS message ids
DMS_GET_MANUFACTURER = 0x0021
DMS_GET_MODEL = 0x0022
DMS_GET_REVISION = 0x0023
DMS_GET_MSISDN = 0x0024
DMS_GET_HARDWARE_REVISION = 0x002C
DMS_GET_BAND_CAPABILITIES = 0x0045

DL_BW_MHZ = {0: 1.4, 1: 3, 2: 5, 3: 10, 4: 15, 5: 20}
RAT_MODE_BITS = {0: "cdma2000_1x", 1: "evdo", 2: "gsm", 3: "umts",
                 4: "lte", 5: "tdscdma", 6: "nr5g"}

# NR-ARFCN (global raster) -> band, FR1. Order matters: most specific first.
NR_ARFCN_BANDS = [
    (620000, 653333, "n78"), (524000, 538000, "n7"), (361000, 376000, "n3"),
    (422000, 434000, "n1"), (386000, 398000, "n2"), (173800, 178800, "n5"),
    (185000, 192000, "n8"), (151600, 160600, "n28"), (158200, 164200, "n20"),
    (460000, 480000, "n40"), (499200, 537999, "n41"), (636667, 646666, "n48"),
    (422000, 440000, "n66"), (123400, 130400, "n71"), (620000, 680000, "n77"),
    (693334, 733333, "n79"), (514000, 524000, "n38"),
]

# LTE EARFCN DL ranges -> band (TS 36.101 Table 5.7.3-1)
LTE_EARFCN_BANDS = [
    (0, 599, 1), (600, 1199, 2), (1200, 1949, 3), (1950, 2399, 4),
    (2400, 2649, 5), (2650, 2749, 6), (2750, 3449, 7), (3450, 3799, 8),
    (3800, 4149, 9), (4150, 4749, 10), (4750, 4949, 11),
    (5010, 5179, 12), (5180, 5279, 13), (5380, 5479, 14),
    (5730, 5849, 17), (5850, 5999, 18), (6000, 6149, 19),
    (6150, 6449, 20), (6450, 6599, 21), (6600, 7399, 22),
    (7500, 7699, 23), (7700, 8039, 24), (8040, 8689, 25),
    (8690, 9039, 26), (9040, 9209, 27), (9210, 9659, 28),
    (9660, 9769, 29), (9770, 9869, 30), (9870, 9919, 31),
    (9920, 10359, 32), (36000, 36199, 33), (36200, 36349, 34),
    (36350, 36949, 35), (36950, 37549, 36), (37550, 37749, 37),
    (37750, 38249, 38), (38250, 38649, 39), (38650, 39649, 40),
    (39650, 41589, 41), (41590, 43589, 42), (43590, 45589, 43),
    (45590, 46589, 44), (46790, 54539, 46), (55240, 56739, 48),
    (66436, 67335, 66), (68586, 68935, 71),
]


def nr_band_from_arfcn(arfcn):
    for lo, hi, band in NR_ARFCN_BANDS:
        if lo <= arfcn <= hi:
            return band
    return None


def lte_band_from_earfcn(earfcn):
    for lo, hi, band in LTE_EARFCN_BANDS:
        if lo <= earfcn <= hi:
            return band
    return None


def lte_band_from_qmi(enum_val):
    """QmiNasActiveBand enum -> LTE band number.

    The QMI enum follows Qualcomm's internal band list and is NOT linear
    above band 14 (values transcribed from libqmi qmi-enums-nas.h):
    e.g. B33..B40 occupy enums 135..142, so B40 arrives as 142 and the
    naive 'enum - 119' formula mislabels it as band 23. Unknown values
    return None rather than a wrong guess.
    """
    return QMI_ACTIVE_BAND_TO_LTE.get(enum_val)


QMI_ACTIVE_BAND_TO_LTE = {
    120: 1, 121: 2, 122: 3, 123: 4, 124: 5, 125: 6, 126: 7, 127: 8,
    128: 9, 129: 10, 130: 11, 131: 12, 132: 13, 133: 14,
    134: 17,
    143: 18, 144: 19, 145: 20, 146: 21,
    152: 23, 147: 24, 148: 25, 153: 26, 164: 27, 158: 28,
    159: 29, 160: 30, 165: 31, 154: 32,
    135: 33, 136: 34, 137: 35, 138: 36, 139: 37, 140: 38, 141: 39,
    142: 40, 149: 41, 150: 42, 151: 43,
    163: 46, 166: 47, 167: 48, 161: 66, 168: 71,
    155: 125, 156: 126, 157: 127, 162: 250,
}


class QmiError(Exception):
    pass


class QmiService:
    def __init__(self, sock, service_id, version=1):
        self.sock = sock
        self.service_id = service_id
        self.version = version
        self.server = None
        self.txn = 0
        self.lock = threading.Lock()
        self.lookup()

    def lookup(self):
        local = self.sock.getsockname()[0]
        inst = self.version  # low byte = version, high byte = instance id
        pkt = struct.pack("<IIIII", _QRTR_TYPE_NEW_LOOKUP, self.service_id,
                          inst, 0, 0)
        self.sock.sendto(pkt, (local, QRTR_PORT_CTRL))
        self.server = None
        self.sock.settimeout(1.5)
        try:
            while True:
                data, _ = self.sock.recvfrom(4096)
                if len(data) < 20:
                    continue
                cmd, svc, _ins, node, port = struct.unpack("<IIIII", data[:20])
                if cmd == _QRTR_TYPE_NEW_SERVER:
                    if svc == 0 and node == 0 and port == 0:
                        break  # end of listing
                    if svc == self.service_id:
                        self.server = (node, port)
        except socket.timeout:
            pass
        if not self.server:
            raise QmiError(f"QMI service {self.service_id} not found on QRTR")

    def request(self, msgid, tlvs=b"", timeout=3.0):
        with self.lock:
            self.txn = (self.txn + 1) & 0xFFFF or 1
            hdr = struct.pack("<BHHH", 0, self.txn, msgid, len(tlvs))
            self.sock.sendto(hdr + tlvs, self.server)
            self.sock.settimeout(timeout)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    data, addr = self.sock.recvfrom(4096)
                except socket.timeout:
                    break
                if addr != self.server or len(data) < 7:
                    continue
                _flags, txn, mid, ln = struct.unpack("<BHHH", data[:7])
                if txn == self.txn and mid == msgid:
                    return data[7:7 + ln]
            raise QmiError(f"svc {self.service_id} msg 0x{msgid:04x}: timeout")


def parse_tlvs(buf):
    out = {}
    i = 0
    while i + 3 <= len(buf):
        t = buf[i]
        ln = struct.unpack("<H", buf[i + 1:i + 3])[0]
        out.setdefault(t, []).append(buf[i + 3:i + 3 + ln])
        i += 3 + ln
    return out


def check_result(tlvs):
    if 0x02 in tlvs:
        result, error = struct.unpack("<HH", tlvs[0x02][0][:4])
        if result != 0:
            raise QmiError(f"QMI error 0x{error:04x}")


def _s16(b, off):
    return struct.unpack_from("<h", b, off)[0]


def _u16(b, off):
    return struct.unpack_from("<H", b, off)[0]


def _u32(b, off):
    return struct.unpack_from("<I", b, off)[0]


def _i8(v):
    return v - 256 if v > 127 else v


class M3200Modem:
    """High-level, thread-safe accessor. Caches each QMI call for `ttl` secs."""

    def __init__(self, ttl=1.0):
        # one QRTR socket per service: each socket gets its own ephemeral port,
        # so concurrent threads never steal each other's replies
        self.nas = QmiService(self._new_sock(), SVC_NAS)
        self.dms = QmiService(self._new_sock(), SVC_DMS)
        self.socks = (self.nas.sock, self.dms.sock)
        self.ttl = ttl
        self._cache = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def _new_sock():
        s = socket.socket(AF_QIPCRTR, socket.SOCK_DGRAM, 0)
        local = s.getsockname()[0]
        s.bind((local, 0))
        return s

    def close(self):
        for s in getattr(self, "socks", []):
            try:
                s.close()
            except OSError:
                pass

    def _call(self, key, fn):
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        val = fn()
        with self._cache_lock:
            self._cache[key] = (now, val)
        return val

    def _invalidate(self, *keys):
        with self._cache_lock:
            for key in keys:
                self._cache.pop(key, None)

    # ------------------------------------------------------------------
    # signal
    # ------------------------------------------------------------------
    def signal(self):
        return self._call("signal", self._signal)

    def _signal(self):
        tlvs = parse_tlvs(self.nas.request(NAS_GET_SIGNAL_INFO))
        check_result(tlvs)
        out = {}
        if 0x14 in tlvs:  # LTE: rssi i8, rsrq i8, rsrp i16, snr i16 (0.1 dB)
            v = tlvs[0x14][0]
            out["lte"] = {
                "rssi_dbm": _i8(v[0]),
                "rsrq_db": _i8(v[1]),
                "rsrp_dbm": _s16(v, 2),
                "snr_db": _s16(v, 4) / 10.0,
            }
        if 0x17 in tlvs:  # NR5G: rsrp i16, snr i16 (0.1 dB)
            v = tlvs[0x17][0]
            out["nr"] = {"rsrp_dbm": _s16(v, 0), "snr_db": _s16(v, 2) / 10.0}
        if 0x18 in tlvs:  # NR5G extended: rsrq i16 (dB; verified vs msgbus)
            out.setdefault("nr", {})["rsrq_db"] = _s16(tlvs[0x18][0], 0)
        return out

    # ------------------------------------------------------------------
    # system info: serving cells, ids, NR carrier
    # ------------------------------------------------------------------
    def system_info(self):
        return self._call("sysinfo", self._system_info)

    def _system_info(self):
        tlvs = parse_tlvs(self.nas.request(NAS_GET_SYSTEM_INFO))
        check_result(tlvs)
        out = {}
        if 0x19 in tlvs:  # LTE system info (fixed 29-byte layout)
            v = tlvs[0x19][0]
            if len(v) >= 29:
                mcc = v[20:23].decode("ascii", "replace")
                mnc = bytes(b for b in v[23:26] if b != 0xFF).decode("ascii", "replace")
                out["lte"] = {
                    "domain": v[1],
                    "roaming": v[5],
                    "forbidden": v[7],
                    "cell_id": _u32(v, 13) if v[12] else None,
                    "mcc": mcc,
                    "mnc": mnc,
                    "tac": _u16(v, 27) if v[26] else None,
                }
        if 0x4A in tlvs:  # NR5G service status info
            v = tlvs[0x4A][0]
            out["nr"] = {"service_status": v[0], "true_service_status": v[1],
                         "preferred_data_path": bool(v[2])}
        if 0x4E in tlvs:
            out["eutra_with_nr5g"] = bool(tlvs[0x4E][0][0])
        if 0x54 in tlvs:  # NR5G PCI (newer than public libqmi schema)
            out.setdefault("nr", {})["pci"] = _u16(tlvs[0x54][0], 0)
        if 0x60 in tlvs:  # NR5G ARFCN (newer than public libqmi schema)
            arfcn = _u32(tlvs[0x60][0], 0)
            out.setdefault("nr", {}).update(
                {"arfcn": arfcn, "band": nr_band_from_arfcn(arfcn)})
        if 0x5F in tlvs:  # PLMN string ("50502\xff")
            raw = tlvs[0x5F][0]
            txt = bytes(b for b in raw[1:] if b != 0xFF).decode("ascii", "replace")
            out.setdefault("nr", {})["plmn"] = txt
        return out

    # ------------------------------------------------------------------
    # LTE carrier aggregation
    # ------------------------------------------------------------------
    def ca_info(self):
        return self._call("ca", self._ca_info)

    def _ca_info(self):
        tlvs = parse_tlvs(self.nas.request(NAS_GET_LTE_CPHY_CA_INFO))
        check_result(tlvs)
        out = {"pcc": None, "scc": []}
        if 0x13 in tlvs:  # PCC: pci u16, earfcn u16, dl_bw u32, band u16
            v = tlvs[0x13][0]
            earfcn = _u16(v, 2)
            # The EARFCN raster identifies the band unambiguously; prefer it
            # over the active-band enum (some firmware builds populate that
            # field oddly for TDD carriers).
            out["pcc"] = {
                "pci": _u16(v, 0), "earfcn": earfcn,
                "dl_bw_mhz": DL_BW_MHZ.get(_u32(v, 4)),
                "band": lte_band_from_earfcn(earfcn)
                        or lte_band_from_qmi(_u16(v, 8)),
            }
        if 0x15 in tlvs:  # SCC array: count u8 + 13-byte structs
            v = tlvs[0x15][0]
            n = v[0]
            off = 1
            for _ in range(n):
                if off + 13 > len(v):
                    break
                earfcn = _u16(v, off + 2)
                dl_bw = DL_BW_MHZ.get(_u32(v, off + 4))
                # The modem reports unpopulated SCC slots with garbage
                # (unknown bw enum / zero earfcn); drop them so the CA view
                # only shows real carriers.  state is a u8 at +10 (reading a
                # u32 there would bleed into the next 13-byte struct).
                if dl_bw is not None and earfcn:
                    out["scc"].append({
                        "pci": _u16(v, off), "earfcn": earfcn,
                        "dl_bw_mhz": dl_bw,
                        "band": lte_band_from_earfcn(earfcn)
                                or lte_band_from_qmi(_u16(v, off + 8)),
                        "state": v[off + 10],
                    })
                off += 13
        total = (out["pcc"]["dl_bw_mhz"] if out["pcc"] else 0) or 0
        total += sum(c["dl_bw_mhz"] or 0 for c in out["scc"])
        out["total_dl_bw_mhz"] = total
        return out

    # ------------------------------------------------------------------
    # serving + neighbour cells
    # ------------------------------------------------------------------
    def cells(self):
        return self._call("cells", self._cells)

    @staticmethod
    def _cell_list(v, off, count):
        cells = []
        for _ in range(count):
            if off + 10 > len(v):
                break
            cells.append({
                "pci": _u16(v, off),
                "rsrq_db": _s16(v, off + 2) / 10.0,
                "rsrp_dbm": _s16(v, off + 4) / 10.0,
                "rssi_dbm": _s16(v, off + 6) / 10.0,
                "sinr_db": _s16(v, off + 8) / 10.0,
            })
            off += 10
        return cells

    def _cells(self):
        tlvs = parse_tlvs(self.nas.request(NAS_GET_CELL_LOCATION_INFO))
        check_result(tlvs)
        out = {"intra_freq": None, "inter_freq": [], "nr": None}
        if 0x13 in tlvs:  # intrafreq LTE (v2 layout, 19-byte header)
            v = tlvs[0x13][0]
            earfcn = _u16(v, 9)
            hdr = {
                "ue_in_idle": bool(v[0]),
                "tac": _u16(v, 3),
                "cell_id": _u32(v, 5),
                "earfcn": earfcn,
                "band": lte_band_from_earfcn(earfcn),
                "serving_pci": _u16(v, 11),
            }
            n = v[18] if len(v) > 18 else 0
            hdr["cells"] = self._cell_list(v, 19, n)
            out["intra_freq"] = hdr
        # 0x30 = interfreq LTE, u32 earfcn variant (supersedes 0x14)
        for v in tlvs.get(0x30, []):
            freqs = []
            n_freq = v[1] if len(v) > 1 else 0
            off = 2
            for _ in range(n_freq):
                if off + 8 > len(v):
                    break
                earfcn = _u32(v, off)
                n_cells = v[off + 7]
                cells = self._cell_list(v, off + 8, n_cells)
                freqs.append({"earfcn": earfcn,
                              "band": lte_band_from_earfcn(earfcn),
                              "cells": cells})
                off += 8 + 10 * n_cells
            out["inter_freq"] = freqs
        if 0x2E in tlvs:
            arfcn = _u32(tlvs[0x2E][0], 0)
            out["nr"] = {"arfcn": arfcn, "band": nr_band_from_arfcn(arfcn)}
        if 0x32 in tlvs:
            raw = tlvs[0x32][0]
            out["plmn"] = bytes(b for b in raw if b != 0xFF).decode("ascii", "replace")
        return out

    # ------------------------------------------------------------------
    # band preferences + hardware capabilities
    # ------------------------------------------------------------------
    def band_prefs(self):
        return self._call("bandprefs", self._band_prefs)

    @staticmethod
    def _bands_from_masks(buf, words):
        vals = struct.unpack("<" + "Q" * words, buf[:8 * words])
        bands = []
        for i, m in enumerate(vals):
            bands += [i * 64 + b + 1 for b in range(64) if m & (1 << b)]
        return bands

    @staticmethod
    def _masks_from_bands(bands, words):
        """Encode 1-based band numbers as little-endian uint64 mask words."""
        masks = [0] * words
        for band in bands:
            if isinstance(band, bool) or not isinstance(band, int):
                raise QmiError("band values must be integers")
            if band < 1 or band > words * 64:
                raise QmiError(f"band {band} is outside 1..{words * 64}")
            index = band - 1
            masks[index // 64] |= 1 << (index % 64)
        return struct.pack("<" + "Q" * words, *masks)

    @staticmethod
    def _tlv(t, payload):
        return struct.pack("<BH", t, len(payload)) + payload

    @staticmethod
    def _validate_band_selection(name, selected, supported):
        selected = sorted(set(selected))
        supported = set(supported)
        if not selected:
            raise QmiError(f"{name} selection must not be empty")
        unsupported = [band for band in selected if band not in supported]
        if unsupported:
            raise QmiError(
                f"{name} selection contains unsupported bands: {unsupported}")
        return selected

    def _band_prefs(self):
        tlvs = parse_tlvs(self.nas.request(NAS_GET_SYSTEM_SELECTION_PREFERENCE))
        check_result(tlvs)
        out = {}
        if 0x11 in tlvs:
            m = _u16(tlvs[0x11][0], 0)
            out["mode_pref_mask"] = m
            out["mode_pref"] = [RAT_MODE_BITS[b] for b in range(8) if m & (1 << b)]
        if 0x15 in tlvs:
            out["lte_bands"] = self._bands_from_masks(tlvs[0x15][0], 1)
        if 0x23 in tlvs:
            out["lte_bands_ext"] = self._bands_from_masks(tlvs[0x23][0], 4)
        if 0x2C in tlvs:
            out["nr5g_sa_bands"] = self._bands_from_masks(tlvs[0x2C][0], 8)
        if 0x2D in tlvs:
            out["nr5g_nsa_bands"] = self._bands_from_masks(tlvs[0x2D][0], 8)
        return out

    def band_capabilities(self):
        return self._call("bandcaps", self._band_capabilities)

    def _band_capabilities(self):
        tlvs = parse_tlvs(self.dms.request(DMS_GET_BAND_CAPABILITIES))
        check_result(tlvs)
        out = {}
        if 0x10 in tlvs:
            out["lte_bands"] = self._bands_from_masks(tlvs[0x10][0], 1)
        # 0x12 is the extended LTE list (including bands above 64); it
        # supersedes the legacy 0x10 mask when present. 0x13 is one generic
        # NR5G capability list, not separate SA/NSA lists.
        if 0x12 in tlvs:
            v = tlvs[0x12][0]
            n = _u16(v, 0)
            extended_lte = [_u16(v, 2 + 2 * i) for i in range(n)
                            if 2 + 2 * i + 2 <= len(v)]
            out["lte_bands"] = extended_lte
            out["lte_bands_ext"] = extended_lte
        if 0x13 in tlvs:
            v = tlvs[0x13][0]
            n = _u16(v, 0)
            nr5g = [_u16(v, 2 + 2 * i) for i in range(n)
                    if 2 + 2 * i + 2 <= len(v)]
            out["nr5g_bands"] = nr5g
            # NAS exposes independent preference masks, but DMS reports one
            # hardware NR capability list. Validate both selections against it.
            out["nr5g_sa_bands"] = nr5g
            out["nr5g_nsa_bands"] = nr5g
        return out

    def set_band_prefs(self, lte_bands, nr5g_sa_bands, nr5g_nsa_bands,
                       duration="power_cycle", allow_empty_nr=False):
        """Set LTE/NR band preferences and return a fresh read-back.

        `duration` is either ``power_cycle`` (QMI value 0) or ``permanent``
        (QMI value 1). The RAT mode preference is intentionally untouched.
        """
        duration_values = {"power_cycle": 0, "permanent": 1}
        if duration not in duration_values:
            raise QmiError("duration must be 'power_cycle' or 'permanent'")

        caps = self.band_capabilities()
        lte = self._validate_band_selection(
            "LTE", lte_bands, caps.get("lte_bands", []))
        nr_sa = (sorted(set(nr5g_sa_bands)) if allow_empty_nr and
                 not nr5g_sa_bands else self._validate_band_selection(
                     "NR5G SA", nr5g_sa_bands,
                     caps.get("nr5g_sa_bands", [])))
        nr_nsa = (sorted(set(nr5g_nsa_bands)) if allow_empty_nr and
                  not nr5g_nsa_bands else self._validate_band_selection(
                      "NR5G NSA", nr5g_nsa_bands,
                      caps.get("nr5g_nsa_bands", [])))

        # Set-message TLV ids differ from Get System Selection Preference:
        # extended LTE 0x24 (GET uses 0x23), NR-SA 0x2f, NR-NSA 0x30.
        tlvs = b"".join((
            self._tlv(0x24, self._masks_from_bands(lte, 4)),
            self._tlv(0x2F, self._masks_from_bands(nr_sa, 8)),
            self._tlv(0x30, self._masks_from_bands(nr_nsa, 8)),
            self._tlv(0x17, struct.pack("<B", duration_values[duration])),
        ))
        result = parse_tlvs(self.nas.request(
            NAS_SET_SYSTEM_SELECTION_PREFERENCE, tlvs, timeout=10.0))
        check_result(result)

        # This firmware acknowledges the SET before the new masks become
        # visible through GET 0x0034 (typically a 1-3 second delay). Poll a
        # fresh read-back so callers don't misreport a successful write.
        expected = {
            "lte_bands": lte,
            "nr5g_sa_bands": nr_sa,
            "nr5g_nsa_bands": nr_nsa,
        }
        deadline = time.monotonic() + 8.0
        actual = {}
        while True:
            self._invalidate("bandprefs")
            actual = self.band_prefs()
            actual_selection = {
                "lte_bands": actual.get("lte_bands_ext") or
                             actual.get("lte_bands") or [],
                "nr5g_sa_bands": actual.get("nr5g_sa_bands") or [],
                "nr5g_nsa_bands": actual.get("nr5g_nsa_bands") or [],
            }
            if actual_selection == expected or time.monotonic() >= deadline:
                return actual
            time.sleep(0.5)

    def set_mode_pref(self, modes, duration="power_cycle"):
        """Set the NAS RAT mode preference and return a verified read-back.

        This changes only the mode-preference TLV; band masks, network
        selection, MCFG/PDC state, and modem operating mode are untouched.
        """
        duration_values = {"power_cycle": 0, "permanent": 1}
        if duration not in duration_values:
            raise QmiError("duration must be 'power_cycle' or 'permanent'")
        if isinstance(modes, (str, bytes)):
            raise QmiError("modes must be a collection of RAT mode names")

        mode_to_bit = {name: bit for bit, name in RAT_MODE_BITS.items()}
        requested = set(modes)
        if not requested:
            raise QmiError("mode preference must not be empty")
        unknown = sorted(requested - set(mode_to_bit))
        if unknown:
            raise QmiError(f"unsupported RAT modes: {unknown}")

        expected = [RAT_MODE_BITS[bit] for bit in sorted(RAT_MODE_BITS)
                    if RAT_MODE_BITS[bit] in requested]
        mask = sum(1 << mode_to_bit[name] for name in requested)
        tlvs = b"".join((
            self._tlv(0x11, struct.pack("<H", mask)),
            self._tlv(0x17, struct.pack("<B", duration_values[duration])),
        ))
        result = parse_tlvs(self.nas.request(
            NAS_SET_SYSTEM_SELECTION_PREFERENCE, tlvs, timeout=10.0))
        check_result(result)

        deadline = time.monotonic() + 8.0
        actual = {}
        while True:
            self._invalidate("bandprefs")
            actual = self.band_prefs()
            if actual.get("mode_pref") == expected or time.monotonic() >= deadline:
                return actual
            time.sleep(0.5)

    def device_info(self):
        return self._call("devinfo", self._device_info)

    def _device_info(self):
        out = {}
        for msgid, key in ((DMS_GET_MANUFACTURER, "manufacturer"),
                           (DMS_GET_MODEL, "model"),
                           (DMS_GET_REVISION, "firmware_revision"),
                           (DMS_GET_HARDWARE_REVISION, "hardware_revision")):
            try:
                tlvs = parse_tlvs(self.dms.request(msgid))
                check_result(tlvs)
                if 0x01 in tlvs:
                    out[key] = tlvs[0x01][0].decode("ascii", "replace").strip("\x00")
            except QmiError:
                pass
        return out

    def endc_config(self):
        return self._call("endc", self._endc_config)

    def _endc_config(self):
        tlvs = parse_tlvs(self.nas.request(NAS_GET_ENDC_CONFIG))
        check_result(tlvs)
        out = {}
        if 0x10 in tlvs:
            out["endc_enabled"] = bool(tlvs[0x10][0][0])
        if 0x11 in tlvs:
            out["immediate_scg_release"] = bool(tlvs[0x11][0][0])
        return out
