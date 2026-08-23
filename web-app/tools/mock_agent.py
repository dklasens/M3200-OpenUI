#!/usr/bin/env python3
"""Mock m3200-agent for local dashboard demos.

Serves realistic M3200 data on :8080 so the dashboard can be reviewed
without the device. Read endpoints return plausible values (with a little
live jitter); mutating endpoints just succeed. CORS is enabled because the
Vite dev server runs on a different port.

Usage:  python3 web-app/tools/mock_agent.py [--port 8080]
"""
import argparse
import json
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOOT = time.time()
MOCK_PASSWORD = "demo"

LTE_CAPS = [1, 2, 3, 4, 5, 7, 8, 12, 13, 17, 18, 19, 20, 25, 26, 28, 40, 42, 43, 48, 66]
NR_CAPS = [1, 3, 5, 7, 8, 28, 78]

STATE = {
    "preferences": {
        "mode_pref_mask": 127,
        "mode_pref": ["cdma2000_1x", "evdo", "gsm", "umts", "lte", "tdscdma", "nr5g"],
        "lte_bands": LTE_CAPS,
        "lte_bands_ext": LTE_CAPS,
        "nr5g_sa_bands": NR_CAPS,
        "nr5g_nsa_bands": [],
    },
    "baseline": {
        "lte_bands": [1, 3, 5, 7, 8, 20, 28],
        "nr5g_sa_bands": [5, 7, 8, 78],
        "nr5g_nsa_bands": [5, 7, 8, 78],
    },
    "logger": {"running": False, "samples": 0, "started": 0,
               "duration": 3600, "interval": 3},
    "update_settings": {"enabled": True, "interval_secs": 604800},
    "bytes_rx": 117_100_577,
    "bytes_tx": 17_028_399,
    "conn_started": BOOT - 201,
}


def jitter(base, pct=0.15):
    return base * (1 + random.uniform(-pct, pct))


# ── Fixture builders ──────────────────────────────────────────────────────────

def signal():
    return {
        "lte": {
            "rssi_dbm": int(jitter(-69, 0.03)),
            "rsrq_db": -11,
            "rsrp_dbm": int(jitter(-102, 0.03)),
            "snr_db": round(jitter(6.4, 0.1), 1),
        },
        "nr": {"rsrp_dbm": None, "snr_db": None, "rsrq_db": None},
    }


def ca_info():
    return {
        "pcc": {"pci": 457, "earfcn": 3350, "dl_bw_mhz": 20, "band": 7},
        "scc": [{"pci": 67, "earfcn": 299, "dl_bw_mhz": 20, "band": 1, "state": 1}],
        "total_dl_bw_mhz": 40,
    }


def system_info():
    return {
        "lte": {"domain": 0, "roaming": 0, "forbidden": 0,
                "cell_id": 0x0139FE3C, "mcc": "505", "mnc": "02", "tac": 51914},
        "nr": {"service_status": 2, "true_service_status": 2,
               "preferred_data_path": True, "pci": 801, "arfcn": 633312,
               "band": "n78", "bandwidth_mhz": 100},
        "eutra_with_nr5g": True,
    }


def cells():
    def cell(pci, rsrp, rsrq, rssi, sinr):
        return {"pci": pci, "rsrq_db": rsrq, "rsrp_dbm": rsrp,
                "rssi_dbm": rssi, "sinr_db": sinr}
    return {
        "intra_freq": {
            "ue_in_idle": False, "tac": 51914, "cell_id": 0x0139FE3C,
            "earfcn": 3350, "band": 7, "serving_pci": 457,
            "cells": [cell(457, -102.1, -11.2, -69.0, 6.4),
                      cell(480, -108.5, -12.0, -74.2, 4.1),
                      cell(198, -113.9, -13.4, -79.8, 1.9)],
        },
        "inter_freq": [{
            "earfcn": 299, "band": 1,
            "cells": [cell(67, -105.3, -11.8, -72.5, 3.3),
                      cell(198, -111.0, -12.9, -77.0, 2.0),
                      cell(423, -116.7, -14.1, -82.4, 0.5)],
        }],
        "nr": None,
        "plmn": "50502",
    }


def dashboard_batch():
    now = time.time()
    dt = max(now - STATE.get("_last_tick", now - 3), 0.5)
    STATE["_last_tick"] = now
    rx_rate = int(jitter(4_200_000, 0.4))
    tx_rate = int(jitter(380_000, 0.4))
    STATE["bytes_rx"] += int(rx_rate * dt)
    STATE["bytes_tx"] += int(tx_rate * dt)
    sysinfo = system_info()
    return {
        "ts": now,
        "signal": signal(),
        "ca": ca_info(),
        "system": sysinfo,
        "endc": {"endc_enabled": True},
        "stock": {
            "statusBarNetwork": "YES OPTUS",
            "statusBarNetworkID": "50502",
            "statusBarTechnology": "LTE",
            "statusBarConnectionState": "Connected",
            "statusBarConnectionDuration": str(int(now - STATE["conn_started"])),
            "statusBarBytesReceived": str(STATE["bytes_rx"]),
            "statusBarBytesTransmitted": str(STATE["bytes_tx"]),
            "statusBarBytesTotal": str(STATE["bytes_rx"] + STATE["bytes_tx"]),
            "statusBarBatteryPercent": "97",
            "statusBarBatteryChargingState": "false",
            "statusBarBatteryChargingSource": "ChargingSourceUSB",
            "statusBarClientListSize": "1",
            "statusBarWiFiEnabled": 0,
            "statusBarWiFiClientListSize": "0",
            "statusBarBand": " B7, n78",
            "statusBarBandwidth": " 20 MHz, 100 MHz",
            "statusBarRoaming": "None",
            "statusBarSimStatus": "Ready",
            "statusBarSignalBars": "3",
            "statusBarSNR": "6",
            "statusBarPCI": "457",
            "statusBarSmsUnreadCount": "0",
            "statusBarAirplaneMode": "AirplaneModeOff",
            "statusBarEthernetPortEnabled": "enabled",
        },
        "mode": "5G NSA",
        "battery": {
            "available": True, "percent": 97, "status": "Discharging",
            "charging": False, "temperature_c": 24.6, "voltage_mv": 3975,
            "current_ma": -628, "health": "Good", "technology": "Li-ion",
            "cycle_count": 0, "charge_full_mah": 4484,
            "charge_full_design_mah": 4484, "time_to_full_secs": None,
            "usb": {"present": True, "online": True, "type": "USB_PD"},
        },
        "thermal": {"available": True, "cpu": round(jitter(32.1, 0.05), 1),
                    "modem": round(jitter(32.4, 0.05), 1),
                    "modem_skin": round(jitter(29.7, 0.05), 1),
                    "battery": 24.6,
                    "charger_skin": round(jitter(28.6, 0.05), 1),
                    "connector": round(jitter(27.6, 0.05), 1),
                    "ambient": round(jitter(29.6, 0.05), 1),
                    "pmic": round(jitter(29.8, 0.05), 1)},
        "cpu": {"overall": round(jitter(18, 0.4), 1), "cores": [round(jitter(18, 0.4), 1)]},
        "memory": {"total_kb": 677_000, "used_kb": 204_000, "free_kb": 473_000,
                   "usage_pct": 30.1},
        "clients": {"count": 1, "wifi_count": 0,
                    "devices": [{"hostname": "Davids-XPS", "interface": "USB"}]},
        "speed": {"rx_bps": rx_rate, "tx_bps": tx_rate,
                  "max_rx_bps": 9_400_000, "max_tx_bps": 1_100_000},
        "device": {
            "manufacturer": "QUALCOMM INCORPORATED", "model": "M3200",
            "firmware_revision": "THN-1.33.1.1-5.4-2.526.1.1-144.1.2-144.1.2",
            "hardware_revision": "SDXLEMUR",
            "imei": "356789012345678", "imsi": "505021234567890",
            "iccid": "89610123456789012345",
            "uptime_secs": int(now - BOOT) + 86_400,
            "load_avg": [0.31, 0.24, 0.2],
        },
        "usage": {"rx_bytes": STATE["bytes_rx"], "tx_bytes": STATE["bytes_tx"],
                  "total_bytes": STATE["bytes_rx"] + STATE["bytes_tx"],
                  "duration_secs": int(now - STATE["conn_started"]),
                  "connected": True},
    }


def bands():
    return {
        "preferences": dict(STATE["preferences"]),
        "capabilities": {
            "lte_bands": LTE_CAPS, "lte_bands_ext": LTE_CAPS,
            "nr5g_bands": NR_CAPS, "nr5g_sa_bands": NR_CAPS,
            "nr5g_nsa_bands": NR_CAPS,
        },
        "control": {"write_enabled": True, "permanent_enabled": True,
                    "baseline": STATE["baseline"]},
    }


def ca_combinations():
    return {
        "schema_version": 1,
        "capture": {"network": "Optus 505-02", "scope": "UECapabilityInformation",
                    "completed_at": 1787360000},
        "summary": {"lte_ca_configurations": 68, "mrdc_configurations": 65,
                    "nr_ca_configurations": 0},
        "lte": [
            {"index": 1, "label": "B7A + B1A", "is_ca": True,
             "components": [{"rat": "lte", "band": 7}, {"rat": "lte", "band": 1}]},
            {"index": 2, "label": "B7A + B28A", "is_ca": True,
             "components": [{"rat": "lte", "band": 7}, {"rat": "lte", "band": 28}]},
            {"index": 3, "label": "B3A + B7A", "is_ca": True,
             "components": [{"rat": "lte", "band": 3}, {"rat": "lte", "band": 7}]},
            {"index": 4, "label": "B7A", "is_ca": False,
             "components": [{"rat": "lte", "band": 7}]},
        ],
        "mrdc": [
            {"index": 1, "label": "B7A + n78A", "is_ca": True,
             "components": [{"rat": "lte", "band": 7}, {"rat": "nr", "band": 78}]},
            {"index": 2, "label": "B3A + n78A", "is_ca": True,
             "components": [{"rat": "lte", "band": 3}, {"rat": "nr", "band": 78}]},
            {"index": 3, "label": "B1A + B3A + n78A", "is_ca": True,
             "components": [{"rat": "lte", "band": 1}, {"rat": "lte", "band": 3},
                            {"rat": "nr", "band": 78}]},
            {"index": 4, "label": "B28A + n78A", "is_ca": True,
             "components": [{"rat": "lte", "band": 28}, {"rat": "nr", "band": 78}]},
        ],
        "nr": [],
        "active": {"key": "lte:pcc:7|lte:scc:1", "label": "B7 (PCC) + B1 (SCC)",
                   "components": [
                       {"rat": "lte", "role": "pcc", "band": 7,
                        "bandwidth_mhz": 20, "pci": 457, "channel": 3350},
                       {"rat": "lte", "role": "scc", "band": 1,
                        "bandwidth_mhz": 20, "pci": 67, "channel": 299}],
                   "first_seen": BOOT - 3600, "last_seen": time.time(),
                   "seen_count": 1200},
        "observed": [
            {"key": "lte:pcc:7|lte:scc:1", "label": "B7 (PCC) + B1 (SCC)",
             "components": [], "first_seen": BOOT - 3600,
             "last_seen": time.time(), "seen_count": 1200},
            {"key": "lte:pcc:7", "label": "B7 (PCC)",
             "components": [], "first_seen": BOOT - 7200,
             "last_seen": BOOT - 1800, "seen_count": 890},
        ],
        "nr_ca_validation": {
            "schema_version": 1,
            "cases": [
                {"requested_sa_bands": [28], "label": "n28 only",
                 "scell_configured": False, "capture": {"completed_at": 1787360000}},
                {"requested_sa_bands": [78], "label": "n78 only",
                 "scell_configured": False, "capture": {"completed_at": 1787360100}},
                {"requested_sa_bands": [1, 28], "label": "n28 (PCC) + n1 (SCell)",
                 "scell_configured": True, "capture": {"completed_at": 1787360200}},
                {"requested_sa_bands": [1, 78], "label": "n1 (PCC) + n78 (SCell)",
                 "scell_configured": True, "capture": {"completed_at": 1787360300}},
            ],
            "conclusion": {"max_component_count": 2},
        },
    }


def nr_ca_validation():
    return ca_combinations()["nr_ca_validation"]


def system_top():
    procs = [
        {"pid": 1911, "name": "wifid", "state": "S", "cpu_pct": 1.2, "rss_kb": 8200},
        {"pid": 673, "name": "wlan_services", "state": "S", "cpu_pct": 0.8, "rss_kb": 6100},
        {"pid": 512, "name": "modem2d", "state": "S", "cpu_pct": 2.4, "rss_kb": 14300},
        {"pid": 480, "name": "webuid", "state": "S", "cpu_pct": 0.5, "rss_kb": 5400},
        {"pid": 1, "name": "systemd", "state": "S", "cpu_pct": 0.1, "rss_kb": 3900},
        {"pid": 2201, "name": "python3", "state": "S", "cpu_pct": 3.1, "rss_kb": 12800},
    ]
    return {"processes": procs, "total_count": 96}


def logger_status():
    log = STATE["logger"]
    elapsed = int(time.time() - log["started"]) if log["running"] else 0
    if log["running"] and elapsed >= log["duration"]:
        log["running"] = False
    return {"running": log["running"], "samples": log["samples"],
            "elapsed_secs": elapsed, "duration_secs": log["duration"],
            "interval_secs": log["interval"],
            "path": "signal-mock.csv" if log["samples"] else None}


SIGNAL_LOG_CSV = (
    "timestamp,lte_rsrp_dbm,lte_rsrq_db,lte_rssi_dbm,lte_snr_db,"
    "nr_rsrp_dbm,nr_rsrq_db,nr_snr_db\n"
    "2026-08-23T10:00:00,-102,-11,-69,6.4,,,\n"
    "2026-08-23T10:00:03,-101,-11,-68,6.9,,,\n"
    "2026-08-23T10:00:06,-103,-12,-70,5.8,,,\n"
)


ROUTES_GET = {
    "/api/dashboard": dashboard_batch,
    "/api/signal": signal,
    "/api/ca": ca_info,
    "/api/ca/combinations": ca_combinations,
    "/api/ca/validation": nr_ca_validation,
    "/api/cells": cells,
    "/api/bands": bands,
    "/api/device": lambda: dashboard_batch()["device"],
    "/api/cpu": lambda: dashboard_batch()["cpu"],
    "/api/memory": lambda: dashboard_batch()["memory"],
    "/api/thermal": lambda: dashboard_batch()["thermal"],
    "/api/battery": lambda: dashboard_batch()["battery"],
    "/api/clients": lambda: dashboard_batch()["clients"],
    "/api/clients": lambda: dashboard_batch()["clients"],
    "/api/wifi/status": lambda: {
        "available": True, "feature_enabled": True, "enabled": True,
        "country": "AU", "ap_mode": 1, "max_clients": 32,
        "associated_stations": 1,
        "modes": ["BGN", "BG", "B", "G", "GN", "N2", "ACN2", "A", "N5", "AN",
                  "ACN5.", "AC5ONLY", "BGNPLUSAX", "ACNPLUSAX"],
        "channels": {"2.4": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
                     "5": ["36", "40", "44", "48", "149", "153", "157", "161"]},
        "profiles": [{"interface": "wlan0", "ssid": "M3200-Demo",
                      "security": "WPA2-PSK", "channel": "44"}],
    },
    "/api/sms/list": lambda: {
        "available": True,
        "messages": [
            {"id": 0, "number": "+61412345678", "text": "Welcome to Optus!",
             "date": "2026-08-22 09:15:00", "status": 0},
            {"id": 1, "number": "101", "text": "Your data balance is 40 GB.",
             "date": "2026-08-21 18:02:11", "status": 1},
        ],
    },
    "/api/modem/apn": lambda: {
        "available": True,
        "profiles": [
            {"cid": 1, "protocol": "IPV4V6", "apn": "YESINTERNET"},
            {"cid": 2, "protocol": "IPV6", "apn": "IMS"},
            {"cid": 3, "protocol": "IP", "apn": "HOS"},
            {"cid": 5, "protocol": "IP", "apn": "mms"},
        ],
    },
    "/api/system/top": system_top,
    "/api/logger/signal/status": logger_status,
    "/api/logger/signal/download": lambda: {"csv": SIGNAL_LOG_CSV},
    "/api/update/status": lambda: {
        "repo": "dklasens/M3200-OpenUI", "busy": False, "error": None,
        "current_version": "0.2-beta",
        "last_check": {"ts": time.time(), "result": {
            "repo": "dklasens/M3200-OpenUI", "current_version": "0.2-beta",
            "latest_version": "0.2-beta", "tag": "v0.2-beta",
            "name": "v0.2 beta", "published_at": "2026-08-23T00:00:00Z",
            "notes": "Mock release", "size": 350000,
            "update_available": False, "same_version": True,
        }},
        "last_install": None,
    },
    "/api/update/settings": lambda: dict(STATE["update_settings"]),
}

ROUTES_POST = {
    "/api/bands/apply": lambda body: {
        "ok": True,
        "duration": (body or {}).get("duration", "power_cycle"),
        "requested": {
            "lte_bands": sorted((body or {}).get("lte_bands", [])),
            "nr5g_sa_bands": sorted((body or {}).get("nr5g_sa_bands", [])),
            "nr5g_nsa_bands": sorted((body or {}).get("nr5g_nsa_bands", [])),
        },
        "actual": {
            "lte_bands": sorted((body or {}).get("lte_bands", [])),
            "nr5g_sa_bands": sorted((body or {}).get("nr5g_sa_bands", [])),
            "nr5g_nsa_bands": sorted((body or {}).get("nr5g_nsa_bands", [])),
        },
        "baseline": STATE["baseline"],
    },
    "/api/bands/restore": lambda body: {
        "ok": True,
        "duration": (body or {}).get("duration", "power_cycle"),
        "requested": STATE["baseline"],
        "actual": STATE["baseline"],
        "baseline": STATE["baseline"],
    },
    "/api/system/restart-agent": lambda body: {"restarting": True},
    "/api/device/reboot": lambda body: {"rebooting": True},
    "/api/at/send": lambda body: {
        "command": (body or {}).get("command", "AT+CSQ").upper(),
        "response": "+CSQ: 21,99",
        "elapsed_ms": 42,
    },
    "/api/logger/signal/start": lambda body: (
        STATE["logger"].update(
            running=True, samples=0, started=time.time(),
            duration=int((body or {}).get("duration_secs", 3600)),
            interval=int((body or {}).get("interval_secs", 3))),
        logger_status())[1],
    "/api/logger/signal/stop": lambda body: (
        STATE["logger"].update(running=False), logger_status())[1],
    "/api/update/check": lambda body: {
        "repo": "dklasens/M3200-OpenUI", "current_version": "0.2-beta",
        "latest_version": "0.2-beta", "tag": "v0.2-beta", "name": "v0.2 beta",
        "published_at": "2026-08-23T00:00:00Z", "notes": "Mock release",
        "size": 350000, "update_available": False, "same_version": True,
    },
    "/api/update/install": lambda body: {
        "repo": "dklasens/M3200-OpenUI", "busy": False, "error": None,
        "current_version": "0.2-beta", "last_check": None,
        "last_install": {"started": time.time(), "finished": time.time(),
                         "ok": True, "message": "mock install", "steps": []},
    },
    "/api/auth/password": lambda body: {"changed": True},
}


def put_update_settings(body):
    body = body or {}
    if isinstance(body.get("enabled"), bool):
        STATE["update_settings"]["enabled"] = body["enabled"]
    try:
        interval = int(body.get("interval_secs", 0))
        if 3600 <= interval <= 2592000:
            STATE["update_settings"]["interval_secs"] = interval
    except (TypeError, ValueError):
        pass
    return dict(STATE["update_settings"])


ROUTES_PUT = {
    "/api/update/settings": put_update_settings,
}


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Confirm, X-M3200-Confirm")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/health":
            return self._send({"ok": True, "data": {"ts": time.time()}})
        if path == "/api/auth/login":
            return self._send({"ok": False, "error": "use POST"}, 405)
        fn = ROUTES_GET.get(path)
        if fn:
            return self._send({"ok": True, "data": fn()})
        return self._send({"ok": False, "error": "no such endpoint"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._body()
        if path == "/api/auth/login":
            if (body or {}).get("password") != MOCK_PASSWORD:
                return self._send({"ok": False, "error": "invalid password"}, 401)
            return self._send({"ok": True,
                               "data": {"token": "demo-token", "expires_in": 3600}})
        fn = ROUTES_POST.get(path)
        if fn:
            return self._send({"ok": True, "data": fn(body)})
        return self._send({"ok": False, "error": "no such endpoint"}, 404)

    def do_PUT(self):
        path = self.path.split("?")[0]
        body = self._body()
        fn = ROUTES_PUT.get(path)
        if fn:
            return self._send({"ok": True, "data": fn(body)})
        return self._send({"ok": False, "error": "no such endpoint"}, 404)

    def log_message(self, fmt, *args):  # quiet
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"mock m3200-agent on http://127.0.0.1:{args.port} (password: {MOCK_PASSWORD})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
