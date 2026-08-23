#!/usr/bin/env python3
"""M3200-OpenUI agent: QMI-backed JSON API + dashboard server.

Runs on the device (stdlib-only Python 3). Serves the built dashboard from
``www/`` and a bearer-token JSON API on the same port:

  http://<lan-ip>:8080/                 dashboard (static, no auth)
  http://<lan-ip>:8080/api/health       liveness probe (no auth)
  http://<lan-ip>:8080/api/auth/login   password -> bearer token

Every other ``/api/*`` route requires ``Authorization: Bearer <token>``.
Responses use the envelope ``{"ok": true, "data": ...}`` or
``{"ok": false, "error": "..."}``.

Band writes additionally require the explicit ``X-M3200-Confirm: apply-bands``
header, a same-origin ``Origin`` when one is sent, and either the bearer
token or the root-only ``X-M3200-Write-Token``.
"""
import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import qmi
import update

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
WWW_DIR_NAME = "www"
STOCK_STATUS_URL = "http://127.0.0.1/srv/status"
STOCK_CLIENTS_URL = "http://127.0.0.1/apps_home/devicesrefresh/"

STATE = {"modem": None, "modem_err": None}
STATE_LOCK = threading.Lock()
STOCK_CACHE = {"ts": 0, "data": None}
AT_CACHE = {}
AT_LOCK = threading.Lock()
BAND_WRITE_LOCK = threading.Lock()
CA_OBSERVED_LOCK = threading.Lock()
CA_COMBINATION_CACHE = None
NR_CA_VALIDATION_CACHE = None
CA_OBSERVED = None
AUTH = None
SPEED_STATE = {"prev": None, "max_rx": 0, "max_tx": 0}
CACHE = {}
CACHE_LOCK = threading.Lock()
LOGGER_STATE = {
    "thread": None, "stop": None, "path": None, "started": 0,
    "duration": 0, "interval": 0, "samples": 0,
}
LOGGER_LOCK = threading.Lock()

TOKEN_TTL_SECS = 3600
MAX_TOKENS = 10
HASH_ITERATIONS = 10_000
MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCKOUT_SECS = 30
LOGIN_ATTEMPT_TTL_SECS = 3600

STOCK_KEEP_FIELDS = (
    "statusBarNetwork", "statusBarNetworkID", "statusBarTechnology",
    "statusBarConnectionState", "statusBarConnectionDuration",
    "statusBarBytesReceived", "statusBarBytesTransmitted", "statusBarBytesTotal",
    "statusBarBatteryPercent", "statusBarBatteryChargingState",
    "statusBarBatteryChargingSource", "statusBarClientListSize",
    "statusBarWiFiEnabled", "statusBarWiFiClientListSize",
    "statusBarBand", "statusBarBandwidth", "statusBarRoaming",
    "statusBarSimStatus", "statusBarSignalBars", "statusBarSNR",
    "statusBarPCI", "statusBarSmsUnreadCount", "statusBarAirplaneMode",
    "statusBarEthernetPortEnabled",
)

THERMAL_ZONES = (
    ("cpu", "cpuss-0-step"),
    ("modem", "mdmss-0-step"),
    ("modem_skin", "modem-skin-usr"),
    ("battery", "battery"),
    ("charger_skin", "chg-skin-therm-usr"),
    ("connector", "conn-therm-usr"),
    ("ambient", "modem-ambient-usr"),
    ("pmic", "pm7250b_tz"),
)

# The AT console is allowlisted to read-only queries.  Anything that writes
# modem state (CFUN, COPS=, CGDCONT=, CMGS/CMGD, CUSD=, ...) or is known to
# hang the bridge (CESQ) is rejected before it reaches read_atcmd.
AT_ALLOWED_PREFIXES = (
    "AT+CSQ", "AT+COPS?", "AT+CEREG?", "AT+C5GREG?", "AT+CREG?",
    "AT+CGREG?", "AT+CSCA?", "AT+CPMS?", "AT+CMGL", "AT+CMGR",
    "AT+GSN", "AT+CIMI", "AT+ICCID", "AT+CNUM", "AT+CLAC", "AT+CUSD?",
    "AT+CGDCONT?", "AT+CMGF?",
)

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".map": "application/json",
    ".txt": "text/plain; charset=utf-8",
    ".woff2": "font/woff2",
}


def write_token_path():
    return os.path.join(AGENT_DIR, "write-token")


def band_baseline_path():
    return os.path.join(AGENT_DIR, "band-baseline.json")


def permanent_marker_path():
    return os.path.join(AGENT_DIR, "permanent-band-writes-enabled")


def ca_combinations_path():
    return os.path.join(AGENT_DIR, "ca-combinations.json")


def ca_observed_path():
    return os.path.join(AGENT_DIR, "ca-observed.json")


def nr_ca_validation_path():
    return os.path.join(AGENT_DIR, "nr-ca-validation.json")


def www_dir():
    return os.path.join(AGENT_DIR, WWW_DIR_NAME)


# ----------------------------------------------------------------------
# auth (ported from MU5250 zte-agent auth.rs semantics)
# ----------------------------------------------------------------------

class AuthState:
    def __init__(self, directory):
        self.directory = directory
        self.lock = threading.Lock()
        self.tokens = []
        self.failed_logins = {}
        self.salt = self._load_or_create_salt()
        self.password_hash = None

    def salt_path(self):
        return os.path.join(self.directory, "auth-salt")

    def password_path(self):
        return os.path.join(self.directory, "agent-password")

    def _load_or_create_salt(self):
        try:
            with open(self.salt_path(), "r", encoding="ascii") as f:
                salt = bytes.fromhex(f.read().strip())
            if len(salt) >= 16:
                return salt
        except (OSError, ValueError):
            pass
        salt = secrets.token_bytes(32)
        fd = os.open(self.salt_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(salt.hex() + "\n")
        os.chmod(self.salt_path(), 0o600)
        return salt

    def ensure_password(self):
        """Load the agent password, generating a root-only one on first run."""
        try:
            with open(self.password_path(), "r", encoding="utf-8") as f:
                password = f.read().strip()
        except OSError:
            password = secrets.token_urlsafe(12)
            fd = os.open(self.password_path(),
                         os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(password + "\n")
            os.chmod(self.password_path(), 0o600)
            print("m3200-openui: generated agent password at %s" %
                  self.password_path(), flush=True)
        if password:
            self.set_password(password)

    def set_password(self, password):
        self.password_hash = self._iterated_hash(password)

    def _iterated_hash(self, secret):
        digest = hashlib.sha256(self.salt + secret.encode("utf-8")).digest()
        for _ in range(1, HASH_ITERATIONS):
            digest = hashlib.sha256(self.salt + digest).digest()
        return digest.hex()

    def login(self, credential, client_ip):
        """Return ("ok", token), ("invalid", None) or ("locked", retry_secs)."""
        now = time.time()
        with self.lock:
            attempt = self.failed_logins.get(client_ip)
            if attempt and attempt["count"] >= MAX_LOGIN_ATTEMPTS:
                if now < attempt["locked_until"]:
                    return "locked", int(attempt["locked_until"] - now) + 1
                del self.failed_logins[client_ip]

        if self.password_hash is None or not credential:
            self._record_failed_login(client_ip, now)
            return "invalid", None
        if not hmac.compare_digest(
                self._iterated_hash(credential).encode("utf-8"),
                self.password_hash.encode("utf-8")):
            self._record_failed_login(client_ip, now)
            return "invalid", None

        with self.lock:
            self.failed_logins.pop(client_ip, None)
            token = secrets.token_hex(16)
            self.tokens = [t for t in self.tokens if t["expires"] > now]
            if len(self.tokens) >= MAX_TOKENS:
                self.tokens.pop(0)
            self.tokens.append({"value": token, "expires": now + TOKEN_TTL_SECS})
        return "ok", token

    def _record_failed_login(self, client_ip, now):
        with self.lock:
            self.failed_logins = {
                ip: a for ip, a in self.failed_logins.items()
                if now < a["locked_until"] or
                now - a["last_attempt"] < LOGIN_ATTEMPT_TTL_SECS
            }
            entry = self.failed_logins.setdefault(client_ip, {
                "count": 0, "locked_until": 0, "last_attempt": now,
            })
            entry["count"] += 1
            entry["last_attempt"] = now
            if entry["count"] >= MAX_LOGIN_ATTEMPTS:
                entry["locked_until"] = now + LOGIN_LOCKOUT_SECS

    def validate(self, token):
        """Validate a bearer token, sliding its expiry forward on success."""
        if not token:
            return False
        now = time.time()
        with self.lock:
            self.tokens = [t for t in self.tokens if t["expires"] > now]
            for entry in self.tokens:
                if hmac.compare_digest(entry["value"].encode("utf-8"),
                                       token.encode("utf-8")):
                    entry["expires"] = now + TOKEN_TTL_SECS
                    return True
        return False


def get_auth():
    global AUTH
    if AUTH is None:
        AUTH = AuthState(AGENT_DIR)
        AUTH.ensure_password()
    return AUTH


# ----------------------------------------------------------------------
# modem access
# ----------------------------------------------------------------------

def get_modem():
    with STATE_LOCK:
        if STATE["modem"] is None:
            STATE["modem"] = qmi.M3200Modem(ttl=1.0)
        return STATE["modem"]


def qmi_guard(fn):
    """Run a modem query; on failure drop the cached connection and report."""
    try:
        return fn(get_modem())
    except Exception as e:
        with STATE_LOCK:
            try:
                STATE["modem"].close()
            except Exception:
                pass
            STATE["modem"] = None
            STATE["modem_err"] = str(e)
        raise


def _drop_sentinels(section):
    """Turn QMI 'no value' sentinels into nulls for the UI.

    Raw int16 fields report -32768; 0.1-unit fields (SNR) are already scaled
    by qmi.py, so their sentinel is -3276.8.  No legitimate reading on this
    device approaches -3000, so one threshold covers both.
    """
    if not isinstance(section, dict):
        return section
    out = {}
    for key, value in section.items():
        if isinstance(value, (int, float)) and value <= -3000:
            out[key] = None
        else:
            out[key] = value
    return out


def build_signal():
    signal = qmi_guard(lambda m: m.signal())
    out = {}
    if "lte" in signal:
        out["lte"] = _drop_sentinels(signal["lte"])
    if "nr" in signal:
        out["nr"] = _drop_sentinels(signal["nr"])
    return out


# ----------------------------------------------------------------------
# CA capability data + live observation
# ----------------------------------------------------------------------

def load_ca_combinations():
    global CA_COMBINATION_CACHE
    if CA_COMBINATION_CACHE is None:
        with open(ca_combinations_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("schema_version") != 1:
            raise ValueError("unsupported CA-combination data schema")
        CA_COMBINATION_CACHE = data
    return CA_COMBINATION_CACHE


def load_nr_ca_validation():
    global NR_CA_VALIDATION_CACHE
    if NR_CA_VALIDATION_CACHE is None:
        try:
            with open(nr_ca_validation_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            if data.get("schema_version") != 1:
                raise ValueError("unsupported NR-CA validation data schema")
            NR_CA_VALIDATION_CACHE = data
        except OSError:
            return None
    return NR_CA_VALIDATION_CACHE


def load_observed_ca():
    global CA_OBSERVED
    if CA_OBSERVED is None:
        try:
            with open(ca_observed_path(), "r", encoding="utf-8") as f:
                loaded = json.load(f)
            CA_OBSERVED = {
                item["key"]: item for item in loaded if isinstance(item, dict)
                and item.get("key")
            }
        except (OSError, ValueError):
            CA_OBSERVED = {}
    return CA_OBSERVED


def save_observed_ca(observed):
    path = ca_observed_path()
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(sorted(observed.values(), key=lambda item: item["first_seen"]),
                  f, indent=1)
        f.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def active_ca_snapshot(ca, system, timestamp=None):
    """Normalize the currently scheduled carriers without inferring CA classes."""
    components = []
    ca_available = isinstance(ca, dict) and not ca.get("error")
    if ca_available:
        pcc = ca.get("pcc")
        if isinstance(pcc, dict) and pcc.get("band"):
            components.append({
                "rat": "lte", "role": "pcc", "band": pcc["band"],
                "bandwidth_mhz": pcc.get("dl_bw_mhz"), "pci": pcc.get("pci"),
                "channel": pcc.get("earfcn"),
            })
        for scc in ca.get("scc") or []:
            if not isinstance(scc, dict) or not scc.get("band"):
                continue
            components.append({
                "rat": "lte", "role": "scc", "band": scc["band"],
                "bandwidth_mhz": scc.get("dl_bw_mhz"), "pci": scc.get("pci"),
                "channel": scc.get("earfcn"), "state": scc.get("state"),
            })
    has_lte = any(item["rat"] == "lte" for item in components)
    nr = system.get("nr") if isinstance(system, dict) else None
    if isinstance(nr, dict) and nr.get("band") and nr.get("pci") is not None:
        band = str(nr["band"]).lower().lstrip("n")
        try:
            band = int(band)
        except ValueError:
            pass
        components.append({
            "rat": "nr", "role": "scg" if has_lte else "sa", "band": band,
            "bandwidth_mhz": nr.get("bandwidth_mhz"), "pci": nr.get("pci"),
            "channel": nr.get("arfcn"),
        })
    # Keep the CA view quiet for ordinary single-carrier LTE, but represent
    # standalone NR explicitly.  In SA the LTE CA query normally returns an
    # error, which previously caused the live n-band to disappear entirely.
    if not components or (len(components) < 2 and components[0]["rat"] == "lte"):
        return None
    labels = []
    for item in components:
        prefix = "B" if item["rat"] == "lte" else "n"
        labels.append("{}{} ({})".format(prefix, item["band"], item["role"].upper()))
    key = "|".join("{}:{}:{}".format(
        item["rat"], item["role"], item["band"]) for item in components)
    return {
        "key": key,
        "label": " + ".join(labels),
        "components": components,
        "observed_at": timestamp if timestamp is not None else time.time(),
    }


def record_observed_ca(ca, system, timestamp=None):
    snapshot = active_ca_snapshot(ca, system, timestamp)
    if snapshot is None:
        return None
    with CA_OBSERVED_LOCK:
        observed = load_observed_ca()
        existing = observed.get(snapshot["key"])
        if existing:
            existing["last_seen"] = snapshot["observed_at"]
            existing["seen_count"] = existing.get("seen_count", 1) + 1
            existing["components"] = snapshot["components"]
            return existing
        snapshot["first_seen"] = snapshot.pop("observed_at")
        snapshot["last_seen"] = snapshot["first_seen"]
        snapshot["seen_count"] = 1
        observed[snapshot["key"]] = snapshot
        save_observed_ca(observed)
        return snapshot


def build_ca_combinations():
    modem = get_modem()
    try:
        ca = modem.ca_info()
    except Exception as error:
        # NAS_GET_LTE_CPHY_CA_INFO normally returns 0x004a in NR SA because
        # there is no LTE PHY carrier.  That must not hide the NR serving cell
        # or the decoded capability inventory.
        ca = {"error": str(error)}
    try:
        system = modem.system_info()
    except Exception as error:
        system = {"error": str(error)}
    active = record_observed_ca(ca, system)
    data = dict(load_ca_combinations())
    data["active"] = active
    data["nr_ca_validation"] = load_nr_ca_validation()
    with CA_OBSERVED_LOCK:
        data["observed"] = sorted(
            load_observed_ca().values(), key=lambda item: item["last_seen"],
            reverse=True)
    return data


# ----------------------------------------------------------------------
# band control
# ----------------------------------------------------------------------

def ensure_write_token():
    """Create the persistent write token once, with root-only permissions."""
    path = write_token_path()
    try:
        with open(path, "r", encoding="ascii") as f:
            token = f.read().strip()
        if token:
            return token
    except OSError:
        pass

    token = secrets.token_hex(24)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token + "\n")
    except FileExistsError:
        with open(path, "r", encoding="ascii") as f:
            token = f.read().strip()
    os.chmod(path, 0o600)
    return token


def read_write_token():
    try:
        with open(write_token_path(), "r", encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return ""


def preference_snapshot(preferences, allow_empty_nr=False):
    snapshot = {
        "lte_bands": list(preferences.get("lte_bands_ext") or
                          preferences.get("lte_bands") or []),
        "nr5g_sa_bands": list(preferences.get("nr5g_sa_bands") or []),
        "nr5g_nsa_bands": list(preferences.get("nr5g_nsa_bands") or []),
    }
    if not snapshot["lte_bands"]:
        raise ValueError("cannot capture an incomplete band-preference baseline")
    if not allow_empty_nr and any(
            not snapshot[key] for key in ("nr5g_sa_bands", "nr5g_nsa_bands")):
        raise ValueError("cannot capture an incomplete band-preference baseline")
    if allow_empty_nr and not (
            snapshot["nr5g_sa_bands"] or snapshot["nr5g_nsa_bands"]):
        raise ValueError("at least one NR path must contain a selected band")
    return snapshot


def load_band_baseline():
    try:
        with open(band_baseline_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_band_baseline(preferences):
    """Atomically preserve the pre-write carrier masks on the first write."""
    path = band_baseline_path()
    if os.path.exists(path):
        return load_band_baseline()
    snapshot = preference_snapshot(preferences, allow_empty_nr=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return load_band_baseline()
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, sort_keys=True)
        f.write("\n")
    return snapshot


def apply_band_preferences(selection, duration):
    requested = {
        "lte_bands": selection.get("lte_bands"),
        "nr5g_sa_bands": selection.get("nr5g_sa_bands"),
        "nr5g_nsa_bands": selection.get("nr5g_nsa_bands"),
    }
    if any(not isinstance(v, list) for v in requested.values()):
        raise ValueError("all three band selections must be JSON arrays")
    if not requested["lte_bands"]:
        raise ValueError("at least one LTE anchor band must be selected")
    if not (requested["nr5g_sa_bands"] or requested["nr5g_nsa_bands"]):
        raise ValueError("at least one NR path must contain a selected band")
    if duration not in ("power_cycle", "permanent"):
        raise ValueError("duration must be 'power_cycle' or 'permanent'")
    if duration == "permanent" and not os.path.exists(permanent_marker_path()):
        raise ValueError("permanent band writes are not enabled on this device")

    with BAND_WRITE_LOCK:
        current = qmi_guard(lambda modem: modem.band_prefs())
        baseline = save_band_baseline(current)
        actual = qmi_guard(lambda modem: modem.set_band_prefs(
            requested["lte_bands"], requested["nr5g_sa_bands"],
            requested["nr5g_nsa_bands"], duration=duration,
            allow_empty_nr=True))

    normalized = {
        "lte_bands": sorted(set(requested["lte_bands"])),
        "nr5g_sa_bands": sorted(set(requested["nr5g_sa_bands"])),
        "nr5g_nsa_bands": sorted(set(requested["nr5g_nsa_bands"])),
    }
    actual_snapshot = preference_snapshot(actual, allow_empty_nr=True)
    return {
        "ok": actual_snapshot == normalized,
        "duration": duration,
        "requested": normalized,
        "actual": actual_snapshot,
        "baseline": baseline,
    }


def restore_band_baseline(duration):
    baseline = load_band_baseline()
    if not baseline:
        raise ValueError("no original carrier baseline has been captured")
    return apply_band_preferences(baseline, duration)


# ----------------------------------------------------------------------
# cached device data sources
# ----------------------------------------------------------------------

def cached(key, ttl, fn):
    now = time.monotonic()
    with CACHE_LOCK:
        entry = CACHE.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
    value = fn()
    with CACHE_LOCK:
        CACHE[key] = (now, value)
    return value


def _read_int(path):
    try:
        with open(path, "r", encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _read_str(path):
    try:
        with open(path, "r", encoding="ascii") as f:
            return f.read().strip()
    except OSError:
        return None


def stock_status():
    """Selected fields from the stock REST API (battery, clients, bytes...)."""
    now = time.monotonic()
    if STOCK_CACHE["data"] is not None and now - STOCK_CACHE["ts"] < 3:
        return STOCK_CACHE["data"]
    try:
        with urllib.request.urlopen(STOCK_STATUS_URL, timeout=2) as r:
            data = json.load(r)["statusData"]
        keep = {k: data.get(k) for k in STOCK_KEEP_FIELDS}
    except Exception:
        keep = None
    STOCK_CACHE.update(ts=now, data=keep)
    if keep:
        _update_speed(keep)
    return keep


def _to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _update_speed(stock):
    """Track WAN throughput from the stock byte counters (bytes/sec)."""
    rx = _to_int(stock.get("statusBarBytesReceived"))
    tx = _to_int(stock.get("statusBarBytesTransmitted"))
    if rx is None or tx is None:
        return
    now = time.monotonic()
    previous = SPEED_STATE["prev"]
    SPEED_STATE["prev"] = {"rx": rx, "tx": tx, "ts": now}
    if not previous:
        return
    dt = now - previous["ts"]
    if dt < 0.5 or rx < previous["rx"] or tx < previous["tx"]:
        return
    rx_bps = (rx - previous["rx"]) / dt
    tx_bps = (tx - previous["tx"]) / dt
    SPEED_STATE["last"] = {"rx_bps": rx_bps, "tx_bps": tx_bps, "ts": now}
    SPEED_STATE["max_rx"] = max(SPEED_STATE["max_rx"], rx_bps)
    SPEED_STATE["max_tx"] = max(SPEED_STATE["max_tx"], tx_bps)


def speed_snapshot():
    last = SPEED_STATE.get("last")
    fresh = last and time.monotonic() - last["ts"] < 15
    return {
        "rx_bps": round(last["rx_bps"]) if fresh else 0,
        "tx_bps": round(last["tx_bps"]) if fresh else 0,
        "max_rx_bps": round(SPEED_STATE["max_rx"]),
        "max_tx_bps": round(SPEED_STATE["max_tx"]),
    }


def cpu_snapshot():
    """Overall + per-core CPU usage from /proc/stat deltas."""
    def sample():
        rows = {}
        with open("/proc/stat", "r", encoding="ascii") as f:
            for line in f:
                if line.startswith("cpu"):
                    parts = line.split()
                    values = [int(v) for v in parts[1:]]
                    idle = values[3] + (values[4] if len(values) > 4 else 0)
                    rows[parts[0]] = (sum(values), idle)
        return rows

    current = sample()
    with CACHE_LOCK:
        prev_entry = CACHE.get("cpu_prev")
    if prev_entry is None:
        # First reading after boot/cache flush: take a short second sample so
        # the delta is real instead of reporting a stale zero.
        first = current
        time.sleep(0.2)
        current = sample()
        previous = first
    else:
        previous = prev_entry[1]
    with CACHE_LOCK:
        CACHE["cpu_prev"] = (time.monotonic(), current)

    def pct(name):
        now_total, now_idle = current.get(name, (0, 0))
        prev_total, prev_idle = previous.get(name, (0, 0))
        dt = now_total - prev_total
        if dt <= 0:
            return 0.0
        return round(100.0 * (1.0 - (now_idle - prev_idle) / dt), 1)

    cores = sorted(k for k in current if k != "cpu")
    return {"overall": pct("cpu"), "cores": [pct(c) for c in cores]}


def memory_snapshot():
    info = {}
    with open("/proc/meminfo", "r", encoding="ascii") as f:
        for line in f:
            key, _, rest = line.partition(":")
            info[key.strip()] = int(rest.strip().split()[0])
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", info.get("MemFree", 0))
    used = max(0, total - available)
    return {
        "total_kb": total,
        "used_kb": used,
        "free_kb": available,
        "usage_pct": round(100.0 * used / total, 1) if total else 0.0,
    }


def thermal_snapshot():
    zones = {}
    base = "/sys/class/thermal"
    names = {}
    try:
        for entry in os.listdir(base):
            if entry.startswith("thermal_zone"):
                zone_type = _read_str(os.path.join(base, entry, "type"))
                if zone_type:
                    names[zone_type] = entry
    except OSError:
        return {"available": False}
    for label, zone_type in THERMAL_ZONES:
        entry = names.get(zone_type)
        if not entry:
            continue
        milli = _read_int(os.path.join(base, entry, "temp"))
        if milli is not None:
            zones[label] = round(milli / 1000.0, 1)
    zones["available"] = bool(zones)
    return zones


def battery_snapshot():
    base = "/sys/class/power_supply/battery"
    if not os.path.isdir(base):
        return {"available": False}
    capacity = _read_int(os.path.join(base, "capacity"))
    status = _read_str(os.path.join(base, "status"))
    temp = _read_int(os.path.join(base, "temp"))
    voltage = _read_int(os.path.join(base, "voltage_now"))
    current = _read_int(os.path.join(base, "current_now"))
    charge_full = _read_int(os.path.join(base, "charge_full"))
    charge_design = _read_int(os.path.join(base, "charge_full_design"))
    cycles = _read_int(os.path.join(base, "cycle_count"))
    time_to_full = _read_int(os.path.join(base, "time_to_full_now"))
    out = {
        "available": True,
        "percent": capacity,
        "status": status,
        "charging": status == "Charging",
        "temperature_c": round(temp / 10.0, 1) if temp is not None else None,
        "voltage_mv": round(voltage / 1000.0) if voltage else None,
        "current_ma": round(current / 1000.0) if current is not None else None,
        "health": _read_str(os.path.join(base, "health")),
        "technology": _read_str(os.path.join(base, "technology")),
        "cycle_count": cycles,
        "charge_full_mah": round(charge_full / 1000.0) if charge_full else None,
        "charge_full_design_mah":
            round(charge_design / 1000.0) if charge_design else None,
        "time_to_full_secs": time_to_full if time_to_full not in (-1, None) else None,
    }
    usb_online = _read_int("/sys/class/power_supply/usb/online")
    usb_present = _read_int("/sys/class/power_supply/usb/present")
    out["usb"] = {
        "present": bool(usb_present),
        "online": bool(usb_online),
        "type": _read_str("/sys/class/power_supply/usb/type"),
    }
    return out


def nr_signal_blob():
    """Decode the msgbus NR signal blob (same data the stock UI renders).

    Verified layout (little-endian u32/i32): rsrp@2, rsrq@6, snr@10,
    pci@30, band@34, arfcn@38, bandwidth_mhz@42.  Cross-checked live against
    QMI NAS Get System Info (PCI/ARFCN) before use.
    """
    def fetch():
        try:
            env = dict(os.environ, LD_LIBRARY_PATH="/opt/nvtl/lib")
            out = subprocess.run(
                ["/opt/nvtl/bin/msgbus_cli", "MsgBusGet",
                 "modem2.5g_data_signal_change"],
                capture_output=True, text=True, timeout=5, env=env)
        except Exception:
            return None
        values = []
        for line in out.stdout.splitlines():
            tokens = line.strip().split()
            if not tokens or not all(
                    len(t) == 2 and all(c in "0123456789abcdefABCDEF" for c in t)
                    for t in tokens):
                continue
            try:
                values.extend(int(t, 16) for t in tokens)
            except ValueError:
                continue
        if len(values) < 46:
            return None
        raw = bytes(values)

        def u32(o):
            return int.from_bytes(raw[o:o + 4], "little")

        def i32(o):
            return int.from_bytes(raw[o:o + 4], "little", signed=True)

        blob = {
            "rsrp_dbm": i32(2), "rsrq_db": i32(6), "snr_db": i32(10),
            "pci": u32(30), "band": u32(34), "arfcn": u32(38),
            "bandwidth_mhz": u32(42),
        }
        if not (0 < blob["arfcn"] <= 3279165 and 0 < blob["band"] <= 128 and
                0 < blob["bandwidth_mhz"] <= 400):
            return None
        return blob

    return cached("nr_blob", 3, fetch)


def enrich_nr_bandwidth(system):
    """Attach the live NR channel bandwidth (msgbus) to the QMI NR cell."""
    nr = system.get("nr") if isinstance(system, dict) else None
    if not isinstance(nr, dict) or nr.get("arfcn") is None:
        return system
    blob = nr_signal_blob()
    if blob and blob["arfcn"] == nr.get("arfcn") and blob["pci"] == nr.get("pci"):
        nr["bandwidth_mhz"] = blob["bandwidth_mhz"]
    return system


def clients_snapshot():
    try:
        with urllib.request.urlopen(STOCK_CLIENTS_URL, timeout=3) as r:
            data = json.load(r)
        devices = [{
            "hostname": item.get("hostname") or item.get("name") or "Unknown",
            "interface": item.get("interfaceType"),
        } for item in data.get("connectedDevicesList") or []]
        return {
            "count": data.get("connectedDevicesCount", len(devices)),
            "wifi_count": data.get("wifiDevicesCount"),
            "devices": devices,
        }
    except Exception:
        return {"count": None, "wifi_count": None, "devices": []}


def device_identity():
    info = qmi_guard(lambda m: m.device_info())

    def at1(cmd):
        lines = at_command(cmd)
        return lines[0] if lines else None

    info.setdefault("imei", at1("AT+GSN"))
    info.setdefault("imsi", at1("AT+CIMI"))
    info.setdefault("iccid", at1("AT+ICCID"))
    return info


def build_device():
    identity = cached("device", 300, device_identity)
    out = dict(identity)
    # The vendor DMS "model" string is literally "0" on this firmware.
    if not out.get("model") or out["model"] == "0":
        out["model"] = "M3200"
    for key in ("imei", "imsi", "iccid"):
        value = out.get(key)
        if isinstance(value, str) and value.startswith(("ERROR", "+CME ERROR")):
            out[key] = None
    try:
        with open("/proc/uptime", "r", encoding="ascii") as f:
            out["uptime_secs"] = int(float(f.read().split()[0]))
        with open("/proc/loadavg", "r", encoding="ascii") as f:
            out["load_avg"] = [float(v) for v in f.read().split()[:3]]
    except (OSError, ValueError):
        pass
    return out


def system_top():
    """Process list from /proc with CPU% deltas and RSS, sorted by RSS."""
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, AttributeError):
        clk_tck = 100
    page_kb = 4
    now = time.monotonic()
    procs = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % entry, "r",
                      encoding="ascii", errors="replace") as f:
                raw = f.read()
            comm_start = raw.index("(")
            comm_end = raw.rindex(")")
            comm = raw[comm_start + 1:comm_end]
            fields = raw[comm_end + 2:].split()
            state = fields[0]
            jiffies = int(fields[11]) + int(fields[12])
            with open("/proc/%s/statm" % entry, "r", encoding="ascii") as f:
                rss_pages = int(f.read().split()[1])
        except (OSError, ValueError, IndexError):
            continue
        procs[int(entry)] = {
            "name": comm, "state": state, "jiffies": jiffies,
            "rss_kb": rss_pages * page_kb,
        }

    with CACHE_LOCK:
        previous = CACHE.get("top_prev")
        CACHE["top_prev"] = (now, {pid: p["jiffies"] for pid, p in procs.items()})
    prev_map = previous[1] if previous else {}
    prev_ts = previous[0] if previous else now
    elapsed = max(now - prev_ts, 0.05)

    rows = []
    for pid, proc in procs.items():
        delta = proc["jiffies"] - prev_map.get(pid, proc["jiffies"])
        cpu_pct = round(100.0 * delta / clk_tck / elapsed, 1) if previous else 0.0
        rows.append({
            "pid": pid, "name": proc["name"], "state": proc["state"],
            "cpu_pct": cpu_pct, "rss_kb": proc["rss_kb"],
        })
    rows.sort(key=lambda r: r["rss_kb"], reverse=True)
    return {"processes": rows[:20], "total_count": len(rows)}


# ----------------------------------------------------------------------
# AT console
# ----------------------------------------------------------------------

def at_command(cmd, timeout=6):
    """Run an AT command via the device's atfwd bridge. Cached per command."""
    with AT_LOCK:
        if cmd in AT_CACHE:
            return AT_CACHE[cmd]
        try:
            env = dict(os.environ, LD_LIBRARY_PATH="/opt/nvtl/lib")
            out = subprocess.run(
                ["/opt/nvtl/bin/read_atcmd", cmd],
                capture_output=True, text=True, timeout=timeout, env=env)
            lines = [l.strip() for l in out.stdout.replace("\r", "").split("\n")]
            lines = [l for l in lines if l and l != cmd and l != "OK"]
            AT_CACHE[cmd] = lines
            return lines
        except Exception:
            return []


def at_console(command):
    normalized = " ".join(str(command).split()).upper()
    if not normalized.startswith("AT"):
        raise ValueError("command must start with AT")
    if not any(normalized == p or normalized.startswith(p)
               for p in AT_ALLOWED_PREFIXES):
        raise ValueError(
            "command is not on the read-only AT allowlist")
    started = time.monotonic()
    # CMGL/CMGR read SMS stores; give them room, but never hang the worker.
    timeout = 15 if normalized.startswith(("AT+CMGL", "AT+CMGR")) else 6
    try:
        env = dict(os.environ, LD_LIBRARY_PATH="/opt/nvtl/lib")
        out = subprocess.run(
            ["/opt/nvtl/bin/read_atcmd", normalized],
            capture_output=True, text=True, timeout=timeout, env=env)
        lines = [l.strip() for l in out.stdout.replace("\r", "").split("\n")]
        lines = [l for l in lines if l and l != normalized and l != "OK"]
        response = "\n".join(lines)
    except subprocess.TimeoutExpired:
        raise ValueError("AT command timed out")
    except FileNotFoundError:
        response = ""
    except Exception as e:
        raise ValueError("AT command failed: %s" % e)
    return {
        "command": normalized,
        "response": response,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


# ----------------------------------------------------------------------
# Wi-Fi status (wifi_cli is fork+exec over msgbus; several getters hang
# while the AP is disabled, so every call is timeout-guarded)
# ----------------------------------------------------------------------

WIFI_CLI = "/opt/nvtl/bin/wifi_cli"


def wifi_cli(args, timeout=5):
    try:
        env = dict(os.environ, LD_LIBRARY_PATH="/opt/nvtl/lib")
        out = subprocess.run([WIFI_CLI] + args, capture_output=True,
                             text=True, timeout=timeout, env=env)
    except Exception:
        return None
    return out.stdout


def _wifi_bracket(output, label):
    """Parse `Label ... : [value]` lines out of wifi_cli output."""
    if not output:
        return None
    for line in output.splitlines():
        if label in line and "[" in line and "]" in line:
            return line.split("[", 1)[1].rsplit("]", 1)[0].strip()
    return None


def wifi_status():
    def fetch():
        status = {"available": False}
        enable = wifi_cli(["get_enable"])
        if enable is None:
            return status
        status["available"] = True
        status["feature_enabled"] = _wifi_bracket(
            enable, "Wifi feature is") == "1"
        status["country"] = _wifi_bracket(wifi_cli(["get_settings"]),
                                          "Country Code")
        ap = wifi_cli(["get_ap_settings"])
        for key, label, cast in (
                ("ap_mode", "AP mode is", int),
                ("max_clients", "Max Number of Clients", int)):
            raw = _wifi_bracket(ap, label)
            try:
                status[key] = cast(raw) if raw is not None else None
            except ValueError:
                status[key] = None
        # get_enable reports the master Wi-Fi feature; the AP itself is off
        # while ap_mode is 0 (the stock UI's statusBarWiFiEnabled agrees).
        status["enabled"] = status.get("ap_mode") not in (None, 0)
        sta = wifi_cli(["get_sta_list"])
        raw = _wifi_bracket(sta, "STA associated")
        try:
            status["associated_stations"] = int(raw) if raw is not None else None
        except ValueError:
            status["associated_stations"] = None
        caps = wifi_cli(["get_caps"])
        modes = _wifi_bracket(caps, "Allowed Wifi modes")
        status["modes"] = [m.strip() for m in modes.split(",")
                           if m.strip()] if modes else []
        channels = {}
        if caps:
            for line in caps.splitlines():
                match = re.match(r"\s*Wifi (\S+) (2\.4|5) GHz supported channels\s*:\s*\[(.*)\]",
                                 line)
                if match:
                    seen = channels.setdefault(match.group(2), [])
                    for ch in match.group(3).split(","):
                        ch = ch.strip()
                        if ch and ch not in seen:
                            seen.append(ch)
        status["channels"] = channels
        # SSID/security live in get_ap_profile, which hangs while the AP is
        # disabled; probe briefly and fall back to null.
        profile = wifi_cli(["get_ap_profile"], timeout=3)
        status["profiles"] = []
        if profile:
            current = None
            for line in profile.splitlines():
                if "interface" in line.lower() and "[" in line:
                    current = {"interface": _wifi_bracket(line, "")}
                    status["profiles"].append(current)
                elif current is not None:
                    for key, label in (("ssid", "SSID"),
                                       ("security", "Security"),
                                       ("channel", "Channel")):
                        if label in line:
                            current[key] = _wifi_bracket(line, label)
        return status

    return cached("wifi", 10, fetch)


# ----------------------------------------------------------------------
# SMS (PDU mode; the AT bridge is one-shot so text mode cannot be assumed)
# ----------------------------------------------------------------------

GSM7_TABLE = (
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ ÆæßÉ !\"#¤%&'()*+,-./"
    "0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑܧ¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
GSM7_EXT = {"\x14": "£", "\x28": "{", "\x29": "}", "\x2F": "\\",
            "\x3C": "[", "\x3D": "~", "\x3E": "]", "\x40": "|", "\x65": "€"}


def _gsm7_unpack(data, count):
    codes = []
    bitbuf = 0
    bits = 0
    for byte in data:
        bitbuf |= byte << bits
        bits += 8
        while bits >= 7 and len(codes) < count:
            codes.append(bitbuf & 0x7F)
            bitbuf >>= 7
            bits -= 7
    return codes


def _gsm7_text(codes):
    out = []
    skip = False
    for code in codes:
        if skip:
            out.append(GSM7_EXT.get(chr(code), "?"))
            skip = False
        elif code == 0x1B:
            skip = True
        elif code < len(GSM7_TABLE):
            out.append(GSM7_TABLE[code])
    return "".join(out)


def decode_sms_pdu(hexstr):
    """Decode an SMS-DELIVER PDU; returns {number, text, date} or None."""
    try:
        raw = bytes.fromhex("".join(hexstr.split()))
    except ValueError:
        return None
    try:
        i = 0
        smsc_len = raw[i]
        i += 1 + smsc_len
        first_octet = raw[i]
        i += 1
        if (first_octet & 0x03) != 0:  # only SMS-DELIVER rows belong in the inbox
            return None
        addr_len = raw[i]
        addr_type = raw[i + 1]
        i += 2
        nibbles = []
        for k in range((addr_len + 1) // 2):
            byte = raw[i + k]
            nibbles += [byte & 0x0F, byte >> 4]
        number = "".join("0123456789ABCDEF"[d] for d in nibbles[:addr_len])
        if addr_type & 0x70 == 0x50 and number.endswith("F"):
            number = number[:-1]
        i += (addr_len + 1) // 2
        i += 1  # TP-PID
        dcs = raw[i]
        i += 1
        ts = raw[i:i + 7]

        def bcd(x):
            return (x & 0x0F) * 10 + (x >> 4)

        date = "20%02d-%02d-%02d %02d:%02d:%02d" % (
            bcd(ts[0]), bcd(ts[1]), bcd(ts[2]),
            bcd(ts[3]), bcd(ts[4]), bcd(ts[5]))
        i += 7
        udl = raw[i]
        i += 1
        if dcs & 0x08:  # UCS-2
            text = raw[i:i + udl].decode("utf-16-be", "replace")
        elif dcs & 0x04:  # 8-bit data
            text = raw[i:i + udl].hex()
        else:
            text = _gsm7_text(_gsm7_unpack(raw[i:], udl))
    except IndexError:
        return None
    return {"number": number, "text": text, "date": date}


def sms_list():
    """Read the inbox via AT+CMGL=4 (PDU mode). Not cached: mail arrives."""
    try:
        env = dict(os.environ, LD_LIBRARY_PATH="/opt/nvtl/lib")
        out = subprocess.run(["/opt/nvtl/bin/read_atcmd", "AT+CMGL=4"],
                             capture_output=True, text=True, timeout=15, env=env)
    except Exception:
        return {"available": False, "messages": []}
    lines = [l.strip() for l in out.stdout.replace("\r", "").split("\n")
             if l.strip() and l.strip() not in ("AT+CMGL=4", "OK")]
    messages = []
    for idx, line in enumerate(lines):
        if not line.startswith("+CMGL:"):
            continue
        pdu = None
        if '"' in line:
            pdu = line.split('"', 2)[1]
        elif idx + 1 < len(lines) and not lines[idx + 1].startswith("+"):
            pdu = lines[idx + 1]
        if not pdu:
            continue
        decoded = decode_sms_pdu(pdu)
        if decoded:
            header = line.split(":", 1)[1].split(",")
            decoded["id"] = int(header[0].strip()) if header[0].strip().isdigit() else len(messages)
            decoded["status"] = int(header[1].strip()) if len(header) > 1 and header[1].strip().isdigit() else None
            messages.append(decoded)
    return {"available": True, "messages": messages}


def apn_profiles():
    lines = at_command("AT+CGDCONT?")
    profiles = []
    for line in lines:
        if not line.startswith("+CGDCONT:"):
            continue
        parts = [p.strip().strip('"') for p in line.split(":", 1)[1].split(",")]
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        profiles.append({
            "cid": int(parts[0]),
            "protocol": parts[1],
            "apn": parts[2],
        })
    return {"available": True, "profiles": profiles}


# ----------------------------------------------------------------------
# signal logger
# ----------------------------------------------------------------------

def logger_status():
    with LOGGER_LOCK:
        stop = LOGGER_STATE["stop"]
        running = bool(LOGGER_STATE["thread"] and
                       LOGGER_STATE["thread"].is_alive() and
                       not (stop and stop.is_set()))
        started = LOGGER_STATE["started"]
        return {
            "running": running,
            "samples": LOGGER_STATE["samples"],
            "elapsed_secs": int(time.time() - started) if started else 0,
            "duration_secs": LOGGER_STATE["duration"],
            "interval_secs": LOGGER_STATE["interval"],
            "path": os.path.basename(LOGGER_STATE["path"] or "") or None,
        }


def logger_start(body):
    duration = int(body.get("duration_secs", 0))
    interval = int(body.get("interval_secs", 0))
    if not 60 <= duration <= 86400:
        raise ValueError("duration_secs must be between 60 and 86400")
    if not 2 <= interval <= 300:
        raise ValueError("interval_secs must be between 2 and 300")
    with LOGGER_LOCK:
        if LOGGER_STATE["thread"] and LOGGER_STATE["thread"].is_alive():
            raise ValueError("signal logger is already running")
        os.makedirs(os.path.join(AGENT_DIR, "logs"), exist_ok=True)
        path = os.path.join(
            AGENT_DIR, "logs",
            "signal-%s.csv" % time.strftime("%Y%m%d-%H%M%S"))
        stop = threading.Event()
        thread = threading.Thread(
            target=logger_loop, args=(path, stop, duration, interval),
            daemon=True)
        LOGGER_STATE.update(thread=thread, stop=stop, path=path,
                            started=time.time(), duration=duration,
                            interval=interval, samples=0)
        thread.start()
    return logger_status()


def logger_stop():
    with LOGGER_LOCK:
        stop = LOGGER_STATE["stop"]
    if stop:
        stop.set()
    return logger_status()


def logger_loop(path, stop, duration, interval):
    with open(path, "w", encoding="ascii") as f:
        f.write("timestamp,lte_rsrp_dbm,lte_rsrq_db,lte_rssi_dbm,lte_snr_db,"
                "nr_rsrp_dbm,nr_rsrq_db,nr_snr_db\n")
        started = time.time()
        while not stop.is_set() and time.time() - started < duration:
            row = [time.strftime("%Y-%m-%dT%H:%M:%S%z")]
            try:
                signal = qmi_guard(lambda m: m.signal())
                lte = signal.get("lte") or {}
                nr = signal.get("nr") or {}

                def cell(section, key):
                    value = section.get(key)
                    if value is None or value <= -3000:
                        return ""
                    return value

                row.extend([
                    cell(lte, "rsrp_dbm"), cell(lte, "rsrq_db"),
                    cell(lte, "rssi_dbm"), cell(lte, "snr_db"),
                    cell(nr, "rsrp_dbm"), cell(nr, "rsrq_db"),
                    cell(nr, "snr_db"),
                ])
            except Exception:
                row.extend([""] * 7)
            f.write(",".join(str(v) for v in row) + "\n")
            f.flush()
            with LOGGER_LOCK:
                LOGGER_STATE["samples"] += 1
            stop.wait(interval)
    with LOGGER_LOCK:
        LOGGER_STATE["thread"] = None


def logger_download():
    with LOGGER_LOCK:
        path = LOGGER_STATE["path"]
    if not path or not os.path.exists(path):
        raise ValueError("no signal log has been recorded")
    with open(path, "r", encoding="ascii") as f:
        csv = f.read(1_000_000)
    return {"csv": csv}


# ----------------------------------------------------------------------
# dashboard batch + status
# ----------------------------------------------------------------------

def derive_mode(ca, system):
    nr = system.get("nr") if isinstance(system, dict) else None
    lte = system.get("lte") if isinstance(system, dict) else None
    nr_active = isinstance(nr, dict) and nr.get("pci") is not None and nr.get("band")
    lte_active = bool((isinstance(lte, dict) and lte.get("cell_id")) or
                      (isinstance(ca, dict) and not ca.get("error") and ca.get("pcc")))
    if nr_active and lte_active:
        return "5G NSA"
    if nr_active:
        return "5G SA"
    if lte_active:
        return "LTE"
    return "searching"


def build_dashboard():
    modem = get_modem()
    data = {"ts": time.time()}
    sections = (("signal", modem.signal), ("ca", modem.ca_info),
                ("system", modem.system_info), ("endc", modem.endc_config))
    errors = 0
    for key, fn in sections:
        try:
            data[key] = fn()
        except Exception as e:
            errors += 1
            data[key] = {"error": str(e)}
    if errors == len(sections):
        # modem link is dead; drop it so the next poll re-discovers QRTR
        with STATE_LOCK:
            try:
                STATE["modem"].close()
            except Exception:
                pass
            STATE["modem"] = None
    if isinstance(data.get("signal"), dict) and "error" not in data["signal"]:
        data["signal"] = {
            k: _drop_sentinels(v) if isinstance(v, dict) else v
            for k, v in data["signal"].items()
        }
    data["mode"] = derive_mode(data.get("ca"), data.get("system"))
    if isinstance(data.get("system"), dict) and "error" not in data["system"]:
        enrich_nr_bandwidth(data["system"])
    data["stock"] = stock_status()
    try:
        record_observed_ca(data.get("ca"), data.get("system"), data["ts"])
    except Exception:
        # Observation history must never make the live status endpoint fail.
        pass

    for key, ttl, fn in (("battery", 10, battery_snapshot),
                         ("thermal", 10, thermal_snapshot),
                         ("cpu", 2, cpu_snapshot),
                         ("memory", 5, memory_snapshot),
                         ("clients", 10, clients_snapshot)):
        try:
            data[key] = cached(key, ttl, fn)
        except Exception:
            data[key] = None
    data["speed"] = speed_snapshot()
    try:
        data["device"] = cached("device", 300, device_identity)
    except Exception as e:
        data["device"] = {"error": str(e)}
    stock = data.get("stock") or {}
    data["usage"] = {
        "rx_bytes": _to_int(stock.get("statusBarBytesReceived")) or 0,
        "tx_bytes": _to_int(stock.get("statusBarBytesTransmitted")) or 0,
        "total_bytes": _to_int(stock.get("statusBarBytesTotal")) or 0,
        "duration_secs": _to_int(stock.get("statusBarConnectionDuration")) or 0,
        "connected": stock.get("statusBarConnectionState") == "Connected",
    }
    return data


def build_bands():
    modem = get_modem()
    out = {}
    for key, fn in (("preferences", modem.band_prefs),
                    ("capabilities", modem.band_capabilities)):
        try:
            out[key] = fn()
        except Exception as e:
            out[key] = {"error": str(e)}
    out["control"] = {
        "write_enabled": bool(read_write_token()),
        "permanent_enabled": os.path.exists(permanent_marker_path()),
        "baseline": load_band_baseline(),
    }
    return out


def schedule_system_command(argv, delay=1.0):
    """Run a systemctl command shortly after the HTTP reply has flushed."""
    def run():
        try:
            subprocess.Popen(argv)
        except Exception:
            pass
    timer = threading.Timer(delay, run)
    timer.daemon = True
    timer.start()


# ----------------------------------------------------------------------
# HTTP surface
# ----------------------------------------------------------------------

# The contract: every route the dashboard calls, and nothing else.
# scripts/check-api-contract.py enforces this against web-app/src/data/api.ts.
ROUTES = [
    ("POST", "/api/auth/login"),
    ("GET", "/api/health"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/signal"),
    ("GET", "/api/ca"),
    ("GET", "/api/ca/combinations"),
    ("GET", "/api/ca/validation"),
    ("GET", "/api/cells"),
    ("GET", "/api/bands"),
    ("POST", "/api/bands/apply"),
    ("POST", "/api/bands/restore"),
    ("GET", "/api/device"),
    ("GET", "/api/cpu"),
    ("GET", "/api/memory"),
    ("GET", "/api/thermal"),
    ("GET", "/api/battery"),
    ("GET", "/api/clients"),
    ("GET", "/api/wifi/status"),
    ("GET", "/api/sms/list"),
    ("GET", "/api/modem/apn"),
    ("GET", "/api/system/top"),
    ("POST", "/api/system/restart-agent"),
    ("POST", "/api/device/reboot"),
    ("POST", "/api/at/send"),
    ("POST", "/api/logger/signal/start"),
    ("POST", "/api/logger/signal/stop"),
    ("GET", "/api/logger/signal/status"),
    ("GET", "/api/logger/signal/download"),
    ("GET", "/api/update/status"),
    ("POST", "/api/update/check"),
    ("POST", "/api/update/install"),
]

OPEN_ROUTES = {"/api/health", "/api/auth/login"}
WRITE_ROUTES = {"/api/bands/apply", "/api/bands/restore"}
CONFIRM_ROUTES = {"/api/device/reboot", "/api/system/restart-agent",
                  "/api/update/install"}


class Handler(BaseHTTPRequestHandler):
    server_version = "m3200-openui/0.2"

    # -- response helpers ------------------------------------------------

    def _send(self, code, body, content_type, headers=None, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if not cache:
            self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _ok(self, data, code=200, headers=None):
        body = json.dumps({"ok": True, "data": data}, indent=1).encode()
        self._send(code, body, "application/json", headers)

    def _err(self, code, message):
        body = json.dumps({"ok": False, "error": message}, indent=1).encode()
        self._send(code, body, "application/json")

    def _read_json(self):
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
        if content_type.lower() != "application/json":
            raise ValueError("Content-Type must be application/json")
        body = getattr(self, "raw_body", b"")
        if len(body) < 2 or len(body) > 8192:
            raise ValueError("JSON request body must be between 2 and 8192 bytes")
        try:
            parsed = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("invalid JSON request body")
        if not isinstance(parsed, dict):
            raise ValueError("JSON request body must be an object")
        return parsed

    # -- auth helpers ------------------------------------------------------

    def bearer_token(self):
        header = self.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        return token.strip() if scheme.lower() == "bearer" else ""

    def require_auth(self):
        """Return None when authorized, else (code, message)."""
        if get_auth().validate(self.bearer_token()):
            return None
        return 401, "authentication required"

    def write_auth_error(self):
        if self.headers.get("X-M3200-Confirm") != "apply-bands":
            return 400, "missing explicit band-write confirmation"

        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        allowed_origins = ("http://" + host, "https://" + host)
        if origin and origin not in allowed_origins:
            return 403, "cross-origin band writes are not allowed"

        # Preserve root-token automation for deploy/maintenance scripts.
        expected = read_write_token()
        supplied = self.headers.get("X-M3200-Write-Token", "")
        if expected and supplied and hmac.compare_digest(
                expected.encode("utf-8"), supplied.encode("utf-8")):
            return None

        # The dashboard authenticates with a bearer token from /api/auth/login.
        if get_auth().validate(self.bearer_token()):
            return None
        if origin:
            return 403, "browser band writes require a same-origin session"
        return 401, "authentication required for band writes"

    # -- request plumbing --------------------------------------------------

    def _api_path(self):
        return self.path.split("?")[0].rstrip("/") or "/"

    def _known(self, method, path):
        return (method, path) in set(ROUTES)

    def do_GET(self):
        path = self._api_path()
        if not path.startswith("/api"):
            return self.serve_static(path)
        if not self._known("GET", path):
            return self._err(404, "no such endpoint")
        try:
            if path == "/api/health":
                return self._ok({"ts": time.time()})
            auth_error = self.require_auth()
            if auth_error:
                code, message = auth_error
                return self._err(code, message)
            if path == "/api/dashboard":
                return self._ok(build_dashboard())
            if path == "/api/signal":
                return self._ok(build_signal())
            if path == "/api/ca":
                return self._ok(qmi_guard(lambda m: m.ca_info()))
            if path == "/api/ca/combinations":
                return self._ok(build_ca_combinations())
            if path == "/api/ca/validation":
                return self._ok(load_nr_ca_validation() or {})
            if path == "/api/cells":
                return self._ok(qmi_guard(lambda m: m.cells()))
            if path == "/api/bands":
                return self._ok(build_bands())
            if path == "/api/device":
                return self._ok(build_device())
            if path == "/api/cpu":
                return self._ok(cached("cpu", 2, cpu_snapshot))
            if path == "/api/memory":
                return self._ok(cached("memory", 5, memory_snapshot))
            if path == "/api/thermal":
                return self._ok(cached("thermal", 10, thermal_snapshot))
            if path == "/api/battery":
                return self._ok(cached("battery", 10, battery_snapshot))
            if path == "/api/clients":
                return self._ok(cached("clients", 10, clients_snapshot))
            if path == "/api/wifi/status":
                return self._ok(wifi_status())
            if path == "/api/sms/list":
                return self._ok(sms_list())
            if path == "/api/modem/apn":
                return self._ok(apn_profiles())
            if path == "/api/system/top":
                return self._ok(system_top())
            if path == "/api/logger/signal/status":
                return self._ok(logger_status())
            if path == "/api/logger/signal/download":
                return self._ok(logger_download())
            if path == "/api/update/status":
                return self._ok(dict(update.status(),
                                     current_version=update.current_version(
                                         AGENT_DIR)))
            return self._err(404, "no such endpoint")
        except (ValueError, qmi.QmiError) as e:
            return self._err(400, str(e))
        except Exception as e:
            return self._err(500, str(e))

    def do_POST(self):
        path = self._api_path()
        # Drain the request body up front: replying (e.g. 401/400) with
        # unread body bytes in the socket makes Windows clients see RSTs.
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        self.raw_body = self.rfile.read(length) if length > 0 else b""
        if not path.startswith("/api") or not self._known("POST", path):
            return self._err(404, "no such endpoint")
        try:
            if path == "/api/auth/login":
                return self.handle_login()
            if path in WRITE_ROUTES:
                auth_error = self.write_auth_error()
                if auth_error:
                    code, message = auth_error
                    return self._err(code, message)
                body = self._read_json()
                duration = body.get("duration", "power_cycle")
                if path == "/api/bands/apply":
                    result = apply_band_preferences(body, duration)
                else:
                    result = restore_band_baseline(duration)
                return self._ok(result, 200 if result["ok"] else 409)
            auth_error = self.require_auth()
            if auth_error:
                code, message = auth_error
                return self._err(code, message)
            if path in CONFIRM_ROUTES and self.headers.get("X-Confirm") != "true":
                return self._err(400, "missing X-Confirm: true header")
            if path == "/api/device/reboot":
                schedule_system_command(["systemctl", "reboot"])
                return self._ok({"rebooting": True})
            if path == "/api/system/restart-agent":
                schedule_system_command(["systemctl", "restart", "m3200-agent"])
                return self._ok({"restarting": True})
            body = self._read_json()
            if path == "/api/at/send":
                command = body.get("command")
                if not isinstance(command, str) or not command.strip():
                    return self._err(400, "command is required")
                return self._ok(at_console(command))
            if path == "/api/logger/signal/start":
                return self._ok(logger_start(body))
            if path == "/api/logger/signal/stop":
                return self._ok(logger_stop())
            if path == "/api/update/check":
                try:
                    return self._ok(update.check(AGENT_DIR))
                except Exception as e:
                    return self._err(502, str(e))
            if path == "/api/update/install":
                allow_same = bool(body.get("allow_same", True))
                return self._ok(update.start_install(AGENT_DIR, allow_same))
            return self._err(404, "no such endpoint")
        except (ValueError, qmi.QmiError) as e:
            return self._err(400, str(e))
        except Exception as e:
            return self._err(500, str(e))

    def handle_login(self):
        try:
            body = self._read_json()
        except ValueError as e:
            return self._err(400, str(e))
        password = body.get("password")
        if not isinstance(password, str) or not password:
            return self._err(400, "password is required")
        client_ip = self.client_address[0]
        result, value = get_auth().login(password, client_ip)
        if result == "ok":
            return self._ok({"token": value, "expires_in": TOKEN_TTL_SECS})
        if result == "locked":
            return self._err(423, "too many failed attempts; retry in %ss" % value)
        return self._err(401, "invalid password")

    # -- static dashboard ---------------------------------------------------

    def serve_static(self, path):
        root = www_dir()
        if path == "/legacy":
            return self.serve_file(os.path.join(AGENT_DIR, "dashboard.html"),
                                   "text/html; charset=utf-8")
        if os.path.isdir(root):
            rel = path.lstrip("/")
            candidate = os.path.normpath(os.path.join(root, rel))
            if candidate.startswith(root + os.sep) and os.path.isfile(candidate):
                ext = os.path.splitext(candidate)[1].lower()
                cache = ext in (".js", ".css", ".svg", ".png", ".ico", ".woff2")
                return self.serve_file(
                    candidate, CONTENT_TYPES.get(ext, "application/octet-stream"),
                    cache=cache)
            index = os.path.join(root, "index.html")
            if os.path.isfile(index):
                return self.serve_file(index, "text/html; charset=utf-8")
        # No built dashboard deployed yet: fall back to the legacy single file.
        legacy = os.path.join(AGENT_DIR, "dashboard.html")
        if path == "/" and os.path.isfile(legacy):
            return self.serve_file(legacy, "text/html; charset=utf-8")
        self.send_error(404)

    def serve_file(self, path, content_type, cache=False):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_error(404)
            return
        headers = {"Cache-Control": "public, max-age=3600"} if cache else None
        self._send(200, body, content_type, headers, cache=cache)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.1.1",
                    help="bind address (default: LAN IP 192.168.1.1)")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    ensure_write_token()
    get_auth()
    # Fail fast at startup so systemd restarts us if QRTR isn't ready yet.
    get_modem()
    print(f"m3200-openui agent on http://{args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
