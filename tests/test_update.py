import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agent"))

import update  # noqa: E402


class VersionCompareTests(unittest.TestCase):
    def test_ordering(self):
        self.assertEqual(update.compare_versions("0.2-beta", "0.2"), -1)
        self.assertEqual(update.compare_versions("0.2", "0.2-beta"), 1)
        self.assertEqual(update.compare_versions("0.2-beta", "0.2-beta"), 0)
        self.assertEqual(update.compare_versions("v0.2.1", "0.2-beta"), 1)
        self.assertEqual(update.compare_versions("0.2-beta", "0.3-beta"), -1)
        self.assertEqual(update.compare_versions("1.0", "0.9.9"), 1)

    def test_parse(self):
        self.assertEqual(update.parse_version("v1.2.3-rc.1"),
                         ((1, 2, 3), "rc.1"))
        self.assertEqual(update.parse_version("0.2"), ((0, 2), None))


class SafeExtractTests(unittest.TestCase):
    def tar_with(self, name, content=b"x"):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            data = io.BytesIO(content)
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tar.addfile(info, data)
        buf.seek(0)
        return tarfile.open(fileobj=buf, mode="r")

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                update._safe_extract(self.tar_with("../evil"), tmp)

    def test_rejects_symlinks(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo("link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tar.addfile(info)
        buf.seek(0)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                update._safe_extract(tarfile.open(fileobj=buf, mode="r"), tmp)

    def test_allows_nested_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            update._safe_extract(self.tar_with("m3200-openui/version"), tmp)
            self.assertTrue(os.path.exists(
                os.path.join(tmp, "m3200-openui", "version")))


class FakeGitHubHandler(BaseHTTPRequestHandler):
    server_version = "fake-github"

    def do_GET(self):
        state = self.server.state
        if self.path.startswith("/repos/") and "releases" in self.path:
            body = json.dumps(state["releases"]).encode()
        elif self.path == "/manifest.json":
            body = json.dumps(state["manifest"]).encode()
        elif self.path == "/pkg.tar.gz":
            body = state["tarball"]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def build_package_tarball():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, data):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        add("m3200-openui/version", b"0.3.0\n")
        add("m3200-openui/agent/m3200_agent.py",
            b"AGENT_VERSION = \"0.3.0\"\nprint('staged agent')\n")
        add("m3200-openui/agent/qmi.py", b"print('staged qmi')\n")
        add("m3200-openui/agent/m3200-agent.service", b"[Unit]\n")
        add("m3200-openui/www/index.html", b"<html>staged</html>")
    return buf.getvalue()


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.agent_dir = os.path.join(self.temp.name, "agent-install")
        os.makedirs(os.path.join(self.agent_dir, "www", "assets"))
        with open(os.path.join(self.agent_dir, "m3200_agent.py"), "w") as f:
            f.write("print('old agent')\n")
        with open(os.path.join(self.agent_dir, "version"), "w") as f:
            f.write("0.2-beta\n")
        self.service_dir = os.path.join(self.temp.name, "systemd")
        os.makedirs(self.service_dir)

        tarball = build_package_tarball()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHubHandler)
        self.server.state = {
            "tarball": tarball,
            "manifest": {
                "version": "0.3.0",
                "asset": "pkg.tar.gz",
                "sha256": hashlib.sha256(tarball).hexdigest(),
                "size": len(tarball),
            },
            "releases": [{
                "tag_name": "v0.3.0",
                "name": "v0.3.0",
                "draft": False,
                "published_at": "2026-08-23T00:00:00Z",
                "body": "test release",
                "assets": [
                    {"name": "manifest.json",
                     "browser_download_url": "%s/manifest.json" % base(self.server)},
                    {"name": "pkg.tar.gz",
                     "browser_download_url": "%s/pkg.tar.gz" % base(self.server)},
                ],
            }],
        }
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

        self.original_api = update.API_BASE
        self.original_restart = update.restart_agent
        self.restarted = []
        update.API_BASE = base(self.server)
        update.restart_agent = lambda: self.restarted.append(True)
        os.environ["M3200_UPDATE_REPO"] = "test/M3200-OpenUI"

    def tearDown(self):
        update.API_BASE = self.original_api
        update.restart_agent = self.original_restart
        os.environ.pop("M3200_UPDATE_REPO", None)
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def service_path(self):
        return os.path.join(self.service_dir, "m3200-agent.service")

    def test_check_reports_update_available(self):
        result = update.check(self.agent_dir)
        self.assertTrue(result["update_available"])
        self.assertEqual(result["latest_version"], "0.3.0")
        self.assertEqual(result["current_version"], "0.2-beta")

    def test_install_verifies_applies_and_restarts(self):
        log = update.install(self.agent_dir, service_path=self.service_path())
        self.assertTrue(log["ok"], log)
        self.assertIn("verify", log["steps"])
        with open(os.path.join(self.agent_dir, "m3200_agent.py")) as f:
            self.assertIn("staged agent", f.read())
        with open(os.path.join(self.agent_dir, "m3200_agent.py.prev")) as f:
            self.assertIn("old agent", f.read())
        with open(os.path.join(self.agent_dir, "version")) as f:
            self.assertEqual(f.read().strip(), "0.3.0")
        self.assertTrue(os.path.exists(
            os.path.join(self.agent_dir, "www", "index.html")))
        self.assertTrue(os.path.exists(self.service_path()))
        # The agent restart is scheduled ~1.5 s after the install finishes so
        # the HTTP response can flush first.
        deadline = time.time() + 5
        while not self.restarted and time.time() < deadline:
            time.sleep(0.2)
        self.assertTrue(self.restarted)

    def test_install_refuses_sha_mismatch(self):
        self.server.state["manifest"] = dict(
            self.server.state["manifest"], sha256="0" * 64)
        log = update.install(self.agent_dir, service_path=self.service_path())
        self.assertFalse(log["ok"])
        self.assertIn("sha256", log["message"])
        with open(os.path.join(self.agent_dir, "version")) as f:
            self.assertEqual(f.read().strip(), "0.2-beta")

    def test_install_refuses_downgrade(self):
        self.server.state["manifest"] = dict(
            self.server.state["manifest"], version="0.1")
        log = update.install(self.agent_dir, service_path=self.service_path())
        self.assertFalse(log["ok"])
        self.assertIn("older", log["message"])


class SettingsTests(unittest.TestCase):
    def test_defaults_save_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = update.load_settings(tmp)
            self.assertTrue(settings["enabled"])
            self.assertEqual(settings["interval_secs"], 604800)

            update.save_settings(tmp, enabled=False, interval_secs=86400)
            settings = update.load_settings(tmp)
            self.assertFalse(settings["enabled"])
            self.assertEqual(settings["interval_secs"], 86400)

            with self.assertRaises(ValueError):
                update.save_settings(tmp, interval_secs=10)
            with self.assertRaises(ValueError):
                update.save_settings(tmp, enabled="yes")

    def test_check_due(self):
        on = {"enabled": True, "interval_secs": 100}
        self.assertTrue(update.check_due(on, None, 1))
        self.assertFalse(update.check_due(on, 50, 100))
        self.assertTrue(update.check_due(on, 50, 151))
        off = {"enabled": False, "interval_secs": 100}
        self.assertFalse(update.check_due(off, None, 1))


def base(server):
    return "http://127.0.0.1:%d" % server.server_port


if __name__ == "__main__":
    unittest.main()
