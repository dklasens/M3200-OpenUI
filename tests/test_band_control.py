import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

import qmi  # noqa: E402
import m3200_agent as agent  # noqa: E402


CAPABILITIES = {
    "lte_bands": [1, 2, 3, 7, 28, 48, 66],
    "nr5g_sa_bands": [1, 3, 7, 28, 78],
    "nr5g_nsa_bands": [1, 3, 7, 28, 78],
}

CARRIER_PREFS = {
    "mode_pref": ["umts", "lte", "nr5g"],
    "lte_bands": [1, 3, 7, 28],
    "lte_bands_ext": [1, 3, 7, 28],
    "nr5g_sa_bands": [28, 78],
    "nr5g_nsa_bands": [7, 28, 78],
}


class FakeNas:
    def __init__(self):
        self.calls = []

    def request(self, msgid, tlvs=b"", timeout=3.0):
        self.calls.append((msgid, tlvs, timeout))
        return qmi.M3200Modem._tlv(0x02, struct.pack("<HH", 0, 0))


class QmiBandWriteTests(unittest.TestCase):
    def modem(self):
        modem = qmi.M3200Modem.__new__(qmi.M3200Modem)
        modem.nas = FakeNas()
        modem._cache = {"bandprefs": (0, {"stale": True})}
        modem._cache_lock = threading.Lock()
        modem.band_capabilities = lambda: {k: list(v) for k, v in CAPABILITIES.items()}
        modem.band_prefs = lambda: {
            "lte_bands_ext": [1, 2, 48, 66],
            "nr5g_sa_bands": [1, 78],
            "nr5g_nsa_bands": [1, 78],
        }
        return modem

    def test_set_encodes_documented_set_tlvs(self):
        modem = self.modem()
        actual = modem.set_band_prefs(
            [1, 2, 48, 66], [1, 78], [1, 78], duration="power_cycle")

        self.assertEqual(actual["lte_bands_ext"], [1, 2, 48, 66])
        self.assertEqual(len(modem.nas.calls), 1)
        msgid, payload, timeout = modem.nas.calls[0]
        self.assertEqual(msgid, 0x0033)
        self.assertEqual(timeout, 10.0)
        tlvs = qmi.parse_tlvs(payload)
        self.assertEqual(set(tlvs), {0x17, 0x24, 0x2F, 0x30})
        self.assertEqual(len(tlvs[0x24][0]), 32)
        self.assertEqual(len(tlvs[0x2F][0]), 64)
        self.assertEqual(len(tlvs[0x30][0]), 64)
        self.assertEqual(tlvs[0x17][0], b"\x00")

        lte_words = struct.unpack("<QQQQ", tlvs[0x24][0])
        self.assertEqual(lte_words[0], (1 << 0) | (1 << 1) | (1 << 47))
        self.assertEqual(lte_words[1], 1 << 1)  # B66
        sa_words = struct.unpack("<" + "Q" * 8, tlvs[0x2F][0])
        self.assertEqual(sa_words[0], 1)
        self.assertEqual(sa_words[1], 1 << 13)  # n78
        nsa_words = struct.unpack("<" + "Q" * 8, tlvs[0x30][0])
        self.assertEqual(nsa_words[0], 1)
        self.assertEqual(nsa_words[1], 1 << 13)  # n78
        self.assertNotIn("bandprefs", modem._cache)

    def test_permanent_duration_and_capability_validation(self):
        modem = self.modem()
        modem.band_prefs = lambda: {
            "lte_bands_ext": [1],
            "nr5g_sa_bands": [1],
            "nr5g_nsa_bands": [1],
        }
        modem.set_band_prefs([1], [1], [1], duration="permanent")
        tlvs = qmi.parse_tlvs(modem.nas.calls[0][1])
        self.assertEqual(tlvs[0x17][0], b"\x01")

        with self.assertRaisesRegex(qmi.QmiError, "unsupported bands"):
            modem.set_band_prefs([1, 99], [1], [1])
        with self.assertRaisesRegex(qmi.QmiError, "must not be empty"):
            modem.set_band_prefs([], [1], [1])

    def test_set_polls_past_stale_readback(self):
        modem = self.modem()
        reads = iter((
            {"lte_bands_ext": [1], "nr5g_sa_bands": [1],
             "nr5g_nsa_bands": [1]},
            {"lte_bands_ext": [1, 2], "nr5g_sa_bands": [1, 78],
             "nr5g_nsa_bands": [1, 78]},
        ))
        modem.band_prefs = lambda: next(reads)
        original_sleep = qmi.time.sleep
        qmi.time.sleep = lambda _seconds: None
        try:
            actual = modem.set_band_prefs([1, 2], [1, 78], [1, 78])
        finally:
            qmi.time.sleep = original_sleep
        self.assertEqual(actual["lte_bands_ext"], [1, 2])

    def test_dms_extended_lte_and_generic_nr_capabilities(self):
        class FakeDms:
            @staticmethod
            def request(_msgid):
                success = qmi.M3200Modem._tlv(0x02, struct.pack("<HH", 0, 0))
                legacy_lte = qmi.M3200Modem._tlv(0x10, struct.pack("<Q", 1))
                ext_lte = qmi.M3200Modem._tlv(
                    0x12, struct.pack("<HHH", 2, 1, 66))
                nr = qmi.M3200Modem._tlv(
                    0x13, struct.pack("<HHH", 2, 1, 78))
                return success + legacy_lte + ext_lte + nr

        modem = qmi.M3200Modem.__new__(qmi.M3200Modem)
        modem.dms = FakeDms()
        capabilities = modem._band_capabilities()
        self.assertEqual(capabilities["lte_bands"], [1, 66])
        self.assertEqual(capabilities["lte_bands_ext"], [1, 66])
        self.assertEqual(capabilities["nr5g_bands"], [1, 78])
        self.assertEqual(capabilities["nr5g_sa_bands"], [1, 78])
        self.assertEqual(capabilities["nr5g_nsa_bands"], [1, 78])

    def test_set_mode_pref_encodes_only_mode_and_duration(self):
        modem = self.modem()
        modem.band_prefs = lambda: {"mode_pref": ["lte"]}

        actual = modem.set_mode_pref(["lte"], duration="permanent")

        self.assertEqual(actual["mode_pref"], ["lte"])
        msgid, payload, timeout = modem.nas.calls[0]
        self.assertEqual(msgid, 0x0033)
        self.assertEqual(timeout, 10.0)
        tlvs = qmi.parse_tlvs(payload)
        self.assertEqual(set(tlvs), {0x11, 0x17})
        self.assertEqual(struct.unpack("<H", tlvs[0x11][0])[0], 1 << 4)
        self.assertEqual(tlvs[0x17][0], b"\x01")

        with self.assertRaisesRegex(qmi.QmiError, "unsupported RAT modes"):
            modem.set_mode_pref(["satellite"])
        with self.assertRaisesRegex(qmi.QmiError, "must not be empty"):
            modem.set_mode_pref([])

    def test_controlled_nr_path_allows_one_empty_nr_mask(self):
        modem = self.modem()
        modem.band_prefs = lambda: {
            "lte_bands_ext": [1],
            "nr5g_sa_bands": [],
            "nr5g_nsa_bands": [78],
        }
        actual = modem.set_band_prefs(
            [1], [], [78], allow_empty_nr=True)
        self.assertEqual(actual["nr5g_sa_bands"], [])
        tlvs = qmi.parse_tlvs(modem.nas.calls[0][1])
        self.assertEqual(tlvs[0x2F][0], b"\x00" * 64)


class FakeModem:
    def __init__(self):
        self.preferences = {k: list(v) for k, v in CARRIER_PREFS.items()}

    def band_prefs(self):
        return {k: list(v) for k, v in self.preferences.items()}

    def band_capabilities(self):
        return {k: list(v) for k, v in CAPABILITIES.items()}

    def signal(self):
        return {
            "lte": {"rssi_dbm": -69, "rsrq_db": -11, "rsrp_dbm": -102,
                    "snr_db": 4.0},
            "nr": {"rsrp_dbm": -32768, "snr_db": -3276.8, "rsrq_db": -32768},
        }

    def endc_config(self):
        return {"endc_enabled": True}

    def device_info(self):
        return {"manufacturer": "Inseego", "model": "M3200",
                "firmware_revision": "THN-1.33.1.1"}

    def set_band_prefs(self, lte, sa, nsa, duration="power_cycle",
                       allow_empty_nr=False):
        for selected, key in ((lte, "lte_bands"), (sa, "nr5g_sa_bands"),
                              (nsa, "nr5g_nsa_bands")):
            if ((not selected and (key == "lte_bands" or not allow_empty_nr)) or
                    not set(selected).issubset(CAPABILITIES[key])):
                raise qmi.QmiError("unsupported or empty selection")
        if not sa and not nsa:
            raise qmi.QmiError("both NR paths are empty")
        self.preferences.update(
            lte_bands=list(lte), lte_bands_ext=list(lte),
            nr5g_sa_bands=list(sa), nr5g_nsa_bands=list(nsa))
        return self.band_prefs()

    def ca_info(self):
        return {
            "pcc": {"band": 7, "dl_bw_mhz": 20, "pci": 480, "earfcn": 3350},
            "scc": [{"band": 1, "dl_bw_mhz": 20, "pci": 67,
                     "earfcn": 299, "state": 1}],
            "total_dl_bw_mhz": 40,
        }

    def system_info(self):
        return {"nr": {"band": "n78", "pci": 198, "arfcn": 633312}}

    def close(self):
        pass


class AuthStateTests(unittest.TestCase):
    PASSWORD = "correct-horse"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.auth = agent.AuthState(self.temp.name)
        self.auth.set_password(self.PASSWORD)

    def tearDown(self):
        self.temp.cleanup()

    def login(self, ip="192.168.1.50", password=None):
        return self.auth.login(password or self.PASSWORD, ip)

    def test_lockout_arms_after_max_attempts(self):
        for _ in range(agent.MAX_LOGIN_ATTEMPTS):
            self.assertEqual(self.login(password="wrong")[0], "invalid")
        # Armed: even the correct password is refused while locked out.
        result, retry = self.login()
        self.assertEqual(result, "locked")
        self.assertGreater(retry, 0)

    def test_lockout_is_scoped_to_the_client_ip(self):
        for _ in range(agent.MAX_LOGIN_ATTEMPTS):
            self.login(ip="192.168.1.50", password="wrong")
        self.assertEqual(self.login(ip="192.168.1.50")[0], "locked")
        # A different client is unaffected.
        self.assertEqual(self.login(ip="192.168.1.99")[0], "ok")

    def test_successful_login_clears_failure_count(self):
        for _ in range(agent.MAX_LOGIN_ATTEMPTS - 1):
            self.login(password="wrong")
        self.assertEqual(self.login()[0], "ok")
        # Counter reset, so a fresh full budget of attempts is available.
        for _ in range(agent.MAX_LOGIN_ATTEMPTS):
            self.assertEqual(self.login(password="wrong")[0], "invalid")

    def test_validate_slides_token_expiry(self):
        _, token = self.login()
        with self.auth.lock:
            self.auth.tokens[0]["expires"] = time.time() + 1
        self.assertTrue(self.auth.validate(token))
        with self.auth.lock:
            remaining = self.auth.tokens[0]["expires"] - time.time()
        self.assertGreater(remaining, agent.TOKEN_TTL_SECS - 2)

    def test_validate_rejects_expired_and_unknown_tokens(self):
        _, token = self.login()
        self.assertFalse(self.auth.validate("not-a-real-token"))
        with self.auth.lock:
            self.auth.tokens[0]["expires"] = time.time() - 1
        self.assertFalse(self.auth.validate(token))

    def test_generated_password_file_is_root_only(self):
        fresh = agent.AuthState(self.temp.name)
        fresh.ensure_password()
        path = fresh.password_path()
        self.assertTrue(os.path.exists(path))
        if os.name == "posix":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        self.assertIsNotNone(fresh.password_hash)

    def test_change_password_validates_and_rotates(self):
        self.assertEqual(
            self.auth.change_password("wrong", "newpassword1"),
            "current password is incorrect")
        self.assertEqual(
            self.auth.change_password(self.PASSWORD, "short"),
            "new password must be at least 8 characters")
        self.assertEqual(
            self.auth.change_password(self.PASSWORD, self.PASSWORD),
            "new password must be different from the current one")

        _, kept = self.login()
        self.assertIsNone(self.auth.change_password(
            self.PASSWORD, "fresh-secret-9", keep_token=kept))

        # Old credential is rejected, the new one works, and every session
        # except the kept token was signed out.
        self.assertEqual(self.login(password=self.PASSWORD)[0], "invalid")
        self.assertEqual(self.login(password="fresh-secret-9")[0], "ok")
        self.assertTrue(self.auth.validate(kept))


class SmsPduTests(unittest.TestCase):
    HEADER = "00040B919471060739F400"  # no SMSC, deliver, +49176070934
    SCTS = "99309251619580"

    def test_decodes_ucs2_pdu(self):
        pdu = self.HEADER + "08" + self.SCTS + "04" + "00480069"
        decoded = agent.decode_sms_pdu(pdu)
        self.assertEqual(decoded["number"], "49176070934")
        self.assertEqual(decoded["text"], "Hi")
        self.assertEqual(decoded["date"], "2099-03-29 15:16:59")

    def test_decodes_gsm7_pdu(self):
        pdu = self.HEADER + "00" + self.SCTS + "02" + "CF25"
        decoded = agent.decode_sms_pdu(pdu)
        self.assertEqual(decoded["text"], "OK")

    def test_rejects_status_reports_and_garbage(self):
        self.assertIsNone(agent.decode_sms_pdu("00060B919471060739F400"))
        self.assertIsNone(agent.decode_sms_pdu("zz"))
        self.assertIsNone(agent.decode_sms_pdu("00"))


class AgentHttpTests(unittest.TestCase):
    PASSWORD = "test-dashboard-password"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original_agent_dir = agent.AGENT_DIR
        self.original_auth = agent.AUTH
        agent.AGENT_DIR = self.temp.name
        agent.AUTH = agent.AuthState(self.temp.name)
        agent.AUTH.set_password(self.PASSWORD)
        self.token = "test-token-123"
        with open(agent.write_token_path(), "w", encoding="ascii") as f:
            f.write(self.token)
        with open(agent.ca_combinations_path(), "w", encoding="utf-8") as f:
            json.dump({
                "schema_version": 1,
                "capture": {"network": "test"},
                "summary": {"lte_ca_configurations": 1,
                            "mrdc_configurations": 1,
                            "nr_ca_configurations": 0},
                "lte": [{"index": 1, "label": "B7A + B1A", "is_ca": True,
                         "components": [{"rat": "lte", "band": 7},
                                        {"rat": "lte", "band": 1}]}],
                "mrdc": [], "nr": [],
            }, f)
        agent.CA_COMBINATION_CACHE = None
        agent.NR_CA_VALIDATION_CACHE = None
        agent.CA_OBSERVED = None
        agent.CACHE.clear()
        self.modem = FakeModem()
        agent.STATE = {"modem": self.modem, "modem_err": None}
        self.server = agent.ThreadingHTTPServer(("127.0.0.1", 0), agent.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        agent.AGENT_DIR = self.original_agent_dir
        agent.AUTH = self.original_auth
        agent.CA_COMBINATION_CACHE = None
        agent.NR_CA_VALIDATION_CACHE = None
        agent.CA_OBSERVED = None
        agent.CACHE.clear()
        self.temp.cleanup()

    # -- HTTP helpers ------------------------------------------------------

    def request(self, method, path, body=None, bearer=None, headers=None):
        all_headers = dict(headers or {})
        if bearer:
            all_headers["Authorization"] = "Bearer " + bearer
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            all_headers.setdefault("Content-Type", "application/json")
        request = urllib.request.Request(
            self.base + path, data=data, headers=all_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def get(self, path, bearer=None):
        return self.request("GET", path, bearer=bearer)

    def post(self, path, body=None, bearer=None, headers=None):
        return self.request("POST", path, body=body or {}, bearer=bearer,
                            headers=headers)

    def login(self, password=None):
        status, payload = self.post(
            "/api/auth/login", {"password": password or self.PASSWORD})
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        return payload["data"]["token"]

    @staticmethod
    def all_selection(duration="power_cycle"):
        return {
            "lte_bands": CAPABILITIES["lte_bands"],
            "nr5g_sa_bands": CAPABILITIES["nr5g_sa_bands"],
            "nr5g_nsa_bands": CAPABILITIES["nr5g_nsa_bands"],
            "duration": duration,
        }

    CONFIRM = {"X-M3200-Confirm": "apply-bands"}

    # -- auth + envelope ----------------------------------------------------

    def test_health_and_login_are_open_everything_else_requires_bearer(self):
        status, payload = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

        for path in ("/api/dashboard", "/api/bands", "/api/signal"):
            status, payload = self.get(path)
            self.assertEqual(status, 401, path)
            self.assertFalse(payload["ok"])
            self.assertIn("authentication", payload["error"])

    def test_login_rejects_bad_password_and_accepts_good_one(self):
        status, payload = self.post("/api/auth/login", {"password": "nope"})
        self.assertEqual(status, 401)
        self.assertFalse(payload["ok"])

        token = self.login()
        status, payload = self.get("/api/bands", bearer=token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertIn("preferences", payload["data"])

    def test_login_lockout_returns_423(self):
        for _ in range(agent.MAX_LOGIN_ATTEMPTS):
            self.post("/api/auth/login", {"password": "nope"})
        status, payload = self.post(
            "/api/auth/login", {"password": self.PASSWORD})
        self.assertEqual(status, 423)
        self.assertIn("too many failed attempts", payload["error"])

    def test_dashboard_batches_modem_and_system_sections(self):
        token = self.login()
        status, payload = self.get("/api/dashboard", bearer=token)
        self.assertEqual(status, 200)
        data = payload["data"]
        self.assertEqual(data["signal"]["nr"]["rsrp_dbm"], None)
        self.assertEqual(data["signal"]["lte"]["rsrp_dbm"], -102)
        # FakeModem reports an LTE PCC and an NR carrier at once -> NSA.
        self.assertEqual(data["mode"], "5G NSA")
        self.assertIn("ca", data)
        self.assertIn("battery", data)
        self.assertIn("cpu", data)
        self.assertIn("usage", data)
        self.assertEqual(data["usage"]["connected"], False)

    # -- band writes ----------------------------------------------------------

    def test_apply_requires_confirmation_and_auth(self):
        token = self.login()
        status, payload = self.post(
            "/api/bands/apply", self.all_selection(), bearer=token)
        self.assertEqual(status, 400)
        self.assertIn("confirmation", payload["error"])

        status, _ = self.post(
            "/api/bands/apply", self.all_selection(), headers=self.CONFIRM)
        self.assertEqual(status, 401)

    def test_bearer_write_applies_and_allows_empty_sa(self):
        token = self.login()
        body = self.all_selection()
        body["nr5g_sa_bands"] = []
        status, payload = self.post(
            "/api/bands/apply", body, bearer=token,
            headers=dict(self.CONFIRM, Origin=self.base))
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["data"]["ok"])
        self.assertEqual(self.modem.preferences["nr5g_sa_bands"], [])

        # Reapplying from an already NSA-only state must reuse the existing
        # baseline before validating the intentionally empty SA path.
        status, payload = self.post(
            "/api/bands/apply", body, bearer=token,
            headers=dict(self.CONFIRM, Origin=self.base))
        self.assertEqual(status, 200, payload)

    def test_root_write_token_still_automates_band_writes(self):
        status, payload = self.post(
            "/api/bands/apply", self.all_selection(),
            headers=dict(self.CONFIRM, **{"X-M3200-Write-Token": self.token}))
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["data"]["ok"])

    def test_cross_origin_writes_are_rejected(self):
        token = self.login()
        evil = {"Origin": "http://malicious.invalid"}
        status, _ = self.post(
            "/api/bands/apply", self.all_selection(), bearer=token,
            headers=dict(self.CONFIRM, **evil))
        self.assertEqual(status, 403)

        status, _ = self.post(
            "/api/bands/apply", self.all_selection(),
            headers=dict(self.CONFIRM, **{"X-M3200-Write-Token": self.token},
                         **evil))
        self.assertEqual(status, 403)

    def test_apply_captures_baseline_and_restore_recovers_it(self):
        status, payload = self.post(
            "/api/bands/apply", self.all_selection(),
            headers=dict(self.CONFIRM, **{"X-M3200-Write-Token": self.token}))
        self.assertEqual(status, 200)
        result = payload["data"]
        self.assertTrue(result["ok"])
        self.assertEqual(result["baseline"]["lte_bands"],
                         CARRIER_PREFS["lte_bands_ext"])
        self.assertTrue(os.path.exists(agent.band_baseline_path()))

        status, payload = self.post(
            "/api/bands/restore", {"duration": "power_cycle"},
            headers=dict(self.CONFIRM, **{"X-M3200-Write-Token": self.token}))
        self.assertEqual(status, 200)
        result = payload["data"]
        self.assertTrue(result["ok"])
        self.assertEqual(result["actual"]["lte_bands"],
                         CARRIER_PREFS["lte_bands_ext"])

    def test_permanent_and_invalid_capability_are_rejected(self):
        auth = dict(self.CONFIRM, **{"X-M3200-Write-Token": self.token})
        status, payload = self.post(
            "/api/bands/apply", self.all_selection("permanent"), headers=auth)
        self.assertEqual(status, 400)
        self.assertIn("not enabled", payload["error"])

        body = self.all_selection()
        body["lte_bands"] = [99]
        status, _ = self.post("/api/bands/apply", body, headers=auth)
        self.assertEqual(status, 400)

    # -- destructive system actions --------------------------------------------

    def test_reboot_and_restart_require_x_confirm(self):
        token = self.login()
        status, payload = self.post("/api/device/reboot", bearer=token)
        self.assertEqual(status, 400)
        self.assertIn("X-Confirm", payload["error"])

        status, payload = self.post(
            "/api/system/restart-agent", bearer=token)
        self.assertEqual(status, 400)
        self.assertIn("X-Confirm", payload["error"])

    # -- AT console --------------------------------------------------------------

    def test_at_console_enforces_read_only_allowlist(self):
        token = self.login()
        status, payload = self.post(
            "/api/at/send", {"command": "AT+CFUN=0"}, bearer=token)
        self.assertEqual(status, 400)
        self.assertIn("allowlist", payload["error"])

        status, payload = self.post(
            "/api/at/send", {"command": "AT+CMGS=123"}, bearer=token)
        self.assertEqual(status, 400)
        self.assertIn("allowlist", payload["error"])

        # Allowed queries run through read_atcmd (absent on a dev machine,
        # which surfaces as an empty response rather than an error).
        status, payload = self.post(
            "/api/at/send", {"command": "at+csq"}, bearer=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["command"], "AT+CSQ")

    # -- CA data --------------------------------------------------------------

    def test_ca_combinations_include_active_and_observed_layouts(self):
        token = self.login()
        status, payload = self.get("/api/ca/combinations", bearer=token)
        self.assertEqual(status, 200)
        result = payload["data"]
        self.assertEqual(result["summary"]["lte_ca_configurations"], 1)
        self.assertEqual(
            result["active"]["label"],
            "B7 (PCC) + B1 (SCC) + n78 (SCG)")
        self.assertEqual(len(result["observed"]), 1)
        self.assertEqual(result["observed"][0]["components"][2]["band"], 78)
        self.assertTrue(os.path.exists(agent.ca_observed_path()))

        status, payload = self.get("/api/ca/combinations", bearer=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["observed"][0]["seen_count"], 2)

    def test_ca_combinations_include_diag_validated_nr_scells(self):
        validation = {
            "schema_version": 1,
            "cases": [{
                "requested_sa_bands": [1, 78],
                "label": "n1 (PCC) + n78 (SCell)",
                "scell_configured": True,
            }],
            "conclusion": {"max_component_count": 2},
        }
        with open(agent.nr_ca_validation_path(), "w", encoding="utf-8") as f:
            json.dump(validation, f)
        agent.NR_CA_VALIDATION_CACHE = None
        token = self.login()

        status, payload = self.get("/api/ca/combinations", bearer=token)
        self.assertEqual(status, 200)
        result = payload["data"]
        self.assertEqual(
            result["nr_ca_validation"]["cases"][0]["requested_sa_bands"],
            [1, 78])
        self.assertEqual(
            result["nr_ca_validation"]["conclusion"]["max_component_count"], 2)

        status, payload = self.get("/api/ca/validation", bearer=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["cases"][0]["label"],
                         "n1 (PCC) + n78 (SCell)")

    def test_sa_snapshot_survives_unavailable_lte_ca_query(self):
        snapshot = agent.active_ca_snapshot(
            {"error": "QMI error 0x004a"},
            {"nr": {"band": "n1", "pci": 431, "arfcn": 423410}},
            timestamp=123.0)

        self.assertEqual(snapshot["label"], "n1 (SA)")
        self.assertEqual(snapshot["components"], [{
            "rat": "nr", "role": "sa", "band": 1,
            "bandwidth_mhz": None, "pci": 431, "channel": 423410,
        }])
        self.assertEqual(snapshot["observed_at"], 123.0)

    def test_ca_endpoint_survives_unavailable_lte_ca_query_in_sa(self):
        def unavailable_ca():
            raise qmi.QmiError("QMI error 0x004a")

        self.modem.ca_info = unavailable_ca
        token = self.login()
        status, payload = self.get("/api/ca/combinations", bearer=token)

        self.assertEqual(status, 200)
        result = payload["data"]
        self.assertEqual(result["active"]["label"], "n78 (SA)")
        self.assertEqual(result["active"]["components"][0]["role"], "sa")

    # -- routes table -----------------------------------------------------------

    def test_password_change_over_http(self):
        token = self.login()
        other = self.login()  # a second session that must be signed out
        body = {"current_password": self.PASSWORD,
                "new_password": "brand-new-secret-1"}
        status, _ = self.post("/api/auth/password", body)
        self.assertEqual(status, 401)

        status, payload = self.post("/api/auth/password", body, bearer=token)
        self.assertEqual(status, 200, payload)

        status, _ = self.post("/api/auth/login", {"password": self.PASSWORD})
        self.assertEqual(status, 401)
        # The other session is invalidated; the changing session survives.
        status, _ = self.get("/api/bands", bearer=other)
        self.assertEqual(status, 401)
        status, _ = self.get("/api/bands", bearer=token)
        self.assertEqual(status, 200)
        self.login("brand-new-secret-1")

    def test_update_settings_roundtrip(self):
        token = self.login()
        status, payload = self.get("/api/update/settings", bearer=token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["data"]["enabled"])
        self.assertEqual(payload["data"]["interval_secs"], 604800)

        status, _ = self.request("PUT", "/api/update/settings",
                                 body={"enabled": True})
        self.assertEqual(status, 401)

        status, payload = self.request(
            "PUT", "/api/update/settings",
            body={"enabled": False, "interval_secs": 86400}, bearer=token)
        self.assertEqual(status, 200, payload)
        self.assertFalse(payload["data"]["enabled"])
        self.assertEqual(payload["data"]["interval_secs"], 86400)

        status, _ = self.request("PUT", "/api/update/settings",
                                 body={"interval_secs": 5}, bearer=token)
        self.assertEqual(status, 400)

    def test_network_and_modem_read_endpoints(self):
        token = self.login()
        for path in ("/api/wifi/status", "/api/sms/list", "/api/modem/apn"):
            status, payload = self.get(path, bearer=token)
            self.assertEqual(status, 200, path)
            self.assertIn("available", payload["data"], path)

    def test_update_status_open_to_auth_and_install_requires_confirm(self):
        token = self.login()
        status, payload = self.get("/api/update/status", bearer=token)
        self.assertEqual(status, 200)
        self.assertIn("current_version", payload["data"])

        status, payload = self.post("/api/update/install", {}, bearer=token)
        self.assertEqual(status, 400)
        self.assertIn("X-Confirm", payload["error"])

    def test_routes_table_has_no_duplicates(self):
        pairs = list(agent.ROUTES)
        self.assertEqual(len(pairs), len(set(pairs)))
        self.assertIn(("GET", "/api/dashboard"), pairs)
        self.assertIn(("POST", "/api/auth/login"), pairs)


if __name__ == "__main__":
    unittest.main()
